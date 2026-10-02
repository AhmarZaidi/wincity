fn main() {
    if std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default() == "windows" {
        let mut res = winres::WindowsResource::new();
        res.set_icon("../assets/appicon.ico");
        res.set("ProductName", "WinCity");
        res.set("FileDescription", "WinCity Taskbar Battery Indicator");
        res.set("LegalCopyright", "Copyright (C) 2026 Ahmar Zaidi");
        let _ = res.compile();
    }
}
