use serde::Serialize;
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendStatus {
    phase: &'static str,
    error: Option<String>,
    log_path: Option<String>,
}

pub struct BackendRuntime {
    child: Mutex<Option<Child>>,
    status: Mutex<BackendStatus>,
    stopping: AtomicBool,
}

impl Default for BackendRuntime {
    fn default() -> Self {
        Self {
            child: Mutex::new(None),
            status: Mutex::new(BackendStatus {
                phase: "starting",
                error: None,
                log_path: None,
            }),
            stopping: AtomicBool::new(false),
        }
    }
}

impl BackendRuntime {
    pub fn start(self: &Arc<Self>) {
        let runtime = self.clone();
        thread::spawn(move || {
            if let Err(error) = runtime.start_and_monitor() {
                log::error!("Backend startup failed: {error}");
                let mut status = runtime.status.lock().unwrap();
                status.phase = "failed";
                status.error = Some(error);
            }
        });
    }

    fn ready(&self) {
        let mut status = self.status.lock().unwrap();
        status.phase = "ready";
        status.error = None;
    }

    fn start_and_monitor(&self) -> Result<(), String> {
        match probe_backend() {
            Probe::Ready => {
                // A separately started backend belongs to its owner. Never kill
                // or replace it when this desktop window exits.
                self.ready();
                return Ok(());
            }
            Probe::Occupied(reason) => {
                return Err(format!(
                    "端口 8790 已被旧版后端或其他服务占用，请关闭对应进程后重启。{reason}"
                ));
            }
            Probe::Offline => {}
        }

        let root = project_root()?;
        let python = python_path(&root);
        if !python.is_file() {
            return Err(format!(
                "未找到 Python 环境：{}。请先安装项目依赖。",
                python.display()
            ));
        }
        let log_path = root.join("data").join("logs").join("backend.log");
        fs::create_dir_all(log_path.parent().unwrap()).map_err(|e| e.to_string())?;
        self.status.lock().unwrap().log_path = Some(log_path.display().to_string());
        let mut log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(|e| format!("无法打开后端日志：{e}"))?;
        let _ = writeln!(log, "\n--- Desktop launch (PID {}) ---", std::process::id());
        let stderr = log.try_clone().map_err(|e| e.to_string())?;
        let mut command = Command::new(python);
        command
            .args(["-m", "backend.runner"])
            .current_dir(root)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONUTF8", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::from(log))
            .stderr(Stdio::from(stderr));
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }

        {
            // Hold the child lock through spawn so closing a window during startup
            // cannot leave an unregistered Python process behind.
            let mut child = self.child.lock().unwrap();
            if self.stopping.load(Ordering::Acquire) {
                return Ok(());
            }
            *child = Some(
                command
                    .spawn()
                    .map_err(|e| format!("启动 Python 失败：{e}"))?,
            );
        }

        let deadline = Instant::now() + Duration::from_secs(30);
        while !self.stopping.load(Ordering::Acquire) {
            self.check_child()?;
            if matches!(probe_backend(), Probe::Ready) {
                self.ready();
                // Detect a crashed child after startup instead of retrying an
                // empty page forever without any explanation.
                while !self.stopping.load(Ordering::Acquire) {
                    thread::sleep(Duration::from_millis(500));
                    self.check_child()?;
                }
                return Ok(());
            }
            if Instant::now() >= deadline {
                self.stop_child();
                return Err("后端在 30 秒内未就绪，请查看后端日志后重启。".into());
            }
            thread::sleep(Duration::from_millis(150));
        }
        Ok(())
    }

    fn check_child(&self) -> Result<(), String> {
        let mut child = self.child.lock().unwrap();
        if let Some(process) = child.as_mut() {
            if let Some(status) = process.try_wait().map_err(|e| e.to_string())? {
                *child = None;
                return Err(format!("后端进程已退出（{status}），请查看后端日志。"));
            }
        }
        Ok(())
    }

    fn stop_child(&self) {
        if let Some(mut child) = self.child.lock().unwrap().take() {
            // EOF requests graceful Uvicorn shutdown, including feature cleanup
            // and releasing the shared Arduino connection. It also works when
            // the desktop process crashes and Windows closes its pipe handles.
            drop(child.stdin.take());
            let deadline = Instant::now() + Duration::from_secs(4);
            while Instant::now() < deadline {
                if matches!(child.try_wait(), Ok(Some(_))) {
                    return;
                }
                thread::sleep(Duration::from_millis(50));
            }
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    pub fn stop(&self) {
        self.stopping.store(true, Ordering::Release);
        self.stop_child();
    }
}

#[tauri::command]
pub fn backend_status(runtime: tauri::State<'_, Arc<BackendRuntime>>) -> BackendStatus {
    runtime.status.lock().unwrap().clone()
}

fn python_path(root: &Path) -> PathBuf {
    if cfg!(windows) {
        root.join(".venv").join("Scripts").join("python.exe")
    } else {
        root.join(".venv").join("bin").join("python")
    }
}

fn is_project_root(path: &Path) -> bool {
    path.join("backend").join("main.py").is_file()
        && path.join("frontend").join("package.json").is_file()
}

fn project_root() -> Result<PathBuf, String> {
    if let Some(root) = std::env::var_os("LOCO_BOX_ROOT") {
        let root = PathBuf::from(root);
        return if is_project_root(&root) {
            Ok(root)
        } else {
            Err(format!(
                "LOCO_BOX_ROOT 不是有效的项目目录：{}",
                root.display()
            ))
        };
    }
    // Also work when launched from Explorer or after moving the repository.
    for start in [std::env::current_exe().ok(), std::env::current_dir().ok()]
        .into_iter()
        .flatten()
    {
        if let Some(root) = start.ancestors().find(|path| is_project_root(path)) {
            return Ok(root.to_path_buf());
        }
    }
    let compiled_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    if is_project_root(&compiled_root) {
        return Ok(compiled_root);
    }
    Err("无法找到项目目录。请使用仓库中的 start.bat，或设置 LOCO_BOX_ROOT。".into())
}

enum Probe {
    Ready,
    Offline,
    Occupied(String),
}

fn valid_health_response(response: &str) -> bool {
    let Some((headers, body)) = response.split_once("\r\n\r\n") else {
        return false;
    };
    if !headers
        .lines()
        .next()
        .is_some_and(|line| line.starts_with("HTTP/1.1 200 ") || line.starts_with("HTTP/1.0 200 "))
    {
        return false;
    }
    serde_json::from_str::<serde_json::Value>(body)
        .map(|value| {
            value["service"] == "loco_box" && value["protocol"] == 1 && value["ready"] == true
        })
        .unwrap_or(false)
}

fn probe_backend() -> Probe {
    let address: SocketAddr = "127.0.0.1:8790".parse().unwrap();
    let mut stream = match TcpStream::connect_timeout(&address, Duration::from_millis(250)) {
        Ok(stream) => stream,
        Err(_) => return Probe::Offline,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    if stream
        .write_all(b"GET /api/health HTTP/1.0\r\nHost: 127.0.0.1:8790\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return Probe::Occupied("健康检查请求失败。".into());
    }
    let mut response = String::new();
    if stream.take(8192).read_to_string(&mut response).is_err() {
        return Probe::Occupied("健康检查未能得到有效响应。".into());
    }
    if valid_health_response(&response) {
        Probe::Ready
    } else {
        Probe::Occupied("健康检查身份或版本不匹配。".into())
    }
}

#[cfg(test)]
mod tests {
    use super::valid_health_response;

    #[test]
    fn health_requires_expected_service_protocol_and_readiness() {
        let response = |body: &str| format!("HTTP/1.1 200 OK\r\n\r\n{body}");
        assert!(valid_health_response(&response(
            r#"{"service":"loco_box","protocol":1,"ready":true}"#
        )));
        for body in [
            r#"{"status":"ok"}"#,
            r#"{"service":"another-app","protocol":1,"ready":true}"#,
            r#"{"service":"loco_box","protocol":2,"ready":true}"#,
            r#"{"service":"loco_box","protocol":1,"ready":false}"#,
            "<html>not a backend</html>",
        ] {
            assert!(!valid_health_response(&response(body)));
        }
        assert!(!valid_health_response(
            "HTTP/1.1 503 Service Unavailable\r\n\r\n{\"service\":\"loco_box\",\"protocol\":1,\"ready\":true}"
        ));
    }
}
