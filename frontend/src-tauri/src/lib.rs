mod backend;
mod overlays;

use std::sync::Arc;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            backend::backend_status,
            overlays::toggle_overlay,
            overlays::hide_overlay,
            overlays::is_overlay_visible,
            overlays::show_box_overlay,
            overlays::hide_box_overlay,
            overlays::show_music_overlay,
            overlays::hide_music_overlay
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // The main view renders immediately while Python starts independently.
            let backend = Arc::new(backend::BackendRuntime::default());
            app.manage(backend.clone());
            app.manage(overlays::OverlayPositions::default());
            backend.start();
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() == "main"
                && matches!(event, tauri::WindowEvent::CloseRequested { .. })
            {
                window.app_handle().exit(0);
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                if let Some(backend) = app.try_state::<Arc<backend::BackendRuntime>>() {
                    backend.stop();
                }
            }
        });
}
