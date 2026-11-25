use std::collections::HashMap;
use std::sync::Mutex;
use tauri::{AppHandle, Manager, PhysicalPosition, WebviewUrl, WebviewWindowBuilder};

#[derive(Default)]
pub struct OverlayPositions(Mutex<HashMap<String, PhysicalPosition<i32>>>);

fn show(app: &AppHandle, label: &str, width: f64, height: f64) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(label) {
        return window.show().map_err(|e| e.to_string());
    }
    // Create each WebView only when needed, avoiding three frontend instances
    // and their polling/WebSockets during application startup.
    let window = WebviewWindowBuilder::new(app, label, WebviewUrl::App("index.html".into()))
        .title(label)
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .shadow(false)
        .resizable(false)
        .focused(false)
        .focusable(!matches!(label, "music_overlay" | "pet_overlay"))
        .inner_size(width, height)
        .visible(false)
        .build()
        .map_err(|e| e.to_string())?;
    if let Some(position) = app
        .state::<OverlayPositions>()
        .0
        .lock()
        .map_err(|e| e.to_string())?
        .get(label)
        .copied()
    {
        window.set_position(position).map_err(|e| e.to_string())?;
    }
    window.show().map_err(|e| e.to_string())
}

fn hide(app: &AppHandle, label: &str) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(label) {
        if let Ok(position) = window.outer_position() {
            app.state::<OverlayPositions>()
                .0
                .lock()
                .map_err(|e| e.to_string())?
                .insert(label.into(), position);
        }
        // Release the WebView and connections, but remember its screen position.
        window.destroy().map_err(|e| e.to_string())?;
    }
    Ok(())
}

// WebView creation runs from async commands so Windows WebView2 initialization
// does not deadlock the main UI thread.
#[tauri::command]
pub async fn toggle_overlay(app: AppHandle) -> Result<bool, String> {
    if app.get_webview_window("overlay").is_some() {
        hide(&app, "overlay")?;
        Ok(false)
    } else {
        show(&app, "overlay", 220.0, 110.0)?;
        Ok(true)
    }
}

#[tauri::command]
pub async fn hide_overlay(app: AppHandle) -> Result<(), String> {
    hide(&app, "overlay")
}

#[tauri::command]
pub fn is_overlay_visible(app: AppHandle) -> Result<bool, String> {
    match app.get_webview_window("overlay") {
        Some(window) => window.is_visible().map_err(|e| e.to_string()),
        None => Ok(false),
    }
}

#[tauri::command]
pub async fn show_box_overlay(app: AppHandle) -> Result<(), String> {
    show(&app, "box_overlay", 320.0, 320.0)
}

#[tauri::command]
pub async fn hide_box_overlay(app: AppHandle) -> Result<(), String> {
    hide(&app, "box_overlay")
}

#[tauri::command]
pub async fn show_music_overlay(app: AppHandle) -> Result<(), String> {
    show(&app, "music_overlay", 320.0, 150.0)
}

#[tauri::command]
pub async fn hide_music_overlay(app: AppHandle) -> Result<(), String> {
    hide(&app, "music_overlay")
}

#[tauri::command]
pub async fn show_pet_overlay(app: AppHandle) -> Result<(), String> {
    show(&app, "pet_overlay", 400.0, 360.0)
}

#[tauri::command]
pub async fn hide_pet_overlay(app: AppHandle) -> Result<(), String> {
    hide(&app, "pet_overlay")
}

/// Open the driver publisher's fixed URL only after the user clicks its link.
#[tauri::command]
pub fn open_npcap_download() -> Result<(), String> {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        std::process::Command::new("rundll32.exe")
            .args(["url.dll,FileProtocolHandler", "https://npcap.com/#download"])
            .creation_flags(0x08000000)
            .spawn()
            .map(|_| ())
            .map_err(|error| format!("无法打开浏览器，请访问 https://npcap.com/#download：{error}"))
    }
    #[cfg(not(windows))]
    {
        Err("实时监听需要 Windows；Npcap 下载地址：https://npcap.com/#download".into())
    }
}
