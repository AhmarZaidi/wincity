use std::ffi::c_void;
use std::mem::size_of;
use windows::core::PCWSTR;
use windows::Win32::Foundation::{COLORREF, HWND, POINT, RECT, SIZE};
use windows::Win32::Graphics::Gdi::{
    CreateCompatibleDC, CreateDIBSection, DeleteDC, DeleteObject, GetDC, ReleaseDC,
    SelectObject, BITMAPINFO, BITMAPINFOHEADER, BI_RGB, BLENDFUNCTION,
    DIB_RGB_COLORS, HBITMAP, HDC, HGDIOBJ,
};
use windows::Win32::UI::WindowsAndMessaging::{
    UpdateLayeredWindow, ULW_ALPHA,
};

pub struct BitmapBuffer {
    pub hdc: HDC,
    pub hbmp: HBITMAP,
    pub old_bmp: HGDIOBJ,
    pub bits: *mut u32,
    pub width: i32,
    pub height: i32,
}

impl BitmapBuffer {
    pub fn new(width: i32, height: i32) -> Option<Self> {
        unsafe {
            let screen_dc = GetDC(HWND(std::ptr::null_mut()));
            let hdc = CreateCompatibleDC(screen_dc);
            let _ = ReleaseDC(HWND(std::ptr::null_mut()), screen_dc);

            let bmi = BITMAPINFO {
                bmiHeader: BITMAPINFOHEADER {
                    biSize: size_of::<BITMAPINFOHEADER>() as u32,
                    biWidth: width,
                    biHeight: -height, // top-down
                    biPlanes: 1,
                    biBitCount: 32,
                    biCompression: BI_RGB.0,
                    ..Default::default()
                },
                ..Default::default()
            };

            let mut bits: *mut c_void = std::ptr::null_mut();
            let hbmp = CreateDIBSection(
                hdc,
                &bmi,
                DIB_RGB_COLORS,
                &mut bits,
                None,
                0,
            );

            if let Ok(hbmp) = hbmp {
                if !hbmp.is_invalid() && !bits.is_null() {
                    let old_bmp = SelectObject(hdc, hbmp);
                    return Some(Self {
                        hdc,
                        hbmp,
                        old_bmp,
                        bits: bits as *mut u32,
                        width,
                        height,
                    });
                }
            }
            None
        }
    }

    pub fn clear(&mut self, color: u32) {
        unsafe {
            let len = (self.width * self.height) as usize;
            let slice = std::slice::from_raw_parts_mut(self.bits, len);
            slice.fill(color);
        }
    }

    pub fn set_pixel(&mut self, x: i32, y: i32, color: u32) {
        if x >= 0 && x < self.width && y >= 0 && y < self.height {
            unsafe {
                *self.bits.offset((y * self.width + x) as isize) = color;
            }
        }
    }

    pub fn blend_pixel(&mut self, x: i32, y: i32, src_argb: u32, coverage: f32) {
        if x < 0 || x >= self.width || y < 0 || y >= self.height || coverage <= 0.0 {
            return;
        }
        let src_a = (((src_argb >> 24) & 0xFF) as f32 * coverage) as u32;
        if src_a == 0 {
            return;
        }
        let src_r = (src_argb >> 16) & 0xFF;
        let src_g = (src_argb >> 8) & 0xFF;
        let src_b = src_argb & 0xFF;

        unsafe {
            let idx = (y * self.width + x) as isize;
            let dst = *self.bits.offset(idx);
            let dst_a = (dst >> 24) & 0xFF;
            let dst_r = (dst >> 16) & 0xFF;
            let dst_g = (dst >> 8) & 0xFF;
            let dst_b = dst & 0xFF;

            if dst_a == 0 {
                *self.bits.offset(idx) = (src_a << 24) | (src_r << 16) | (src_g << 8) | src_b;
                return;
            }

            let fa = src_a as f32 / 255.0;
            let inv_fa = 1.0 - fa;

            let out_a = (src_a as f32 + dst_a as f32 * inv_fa).min(255.0) as u32;
            let out_r = (src_r as f32 * fa + dst_r as f32 * inv_fa).min(255.0) as u32;
            let out_g = (src_g as f32 * fa + dst_g as f32 * inv_fa).min(255.0) as u32;
            let out_b = (src_b as f32 * fa + dst_b as f32 * inv_fa).min(255.0) as u32;

            *self.bits.offset(idx) = (out_a << 24) | (out_r << 16) | (out_g << 8) | out_b;
        }
    }

    pub fn fill_rounded_rect(&mut self, x0: i32, y0: i32, x1: i32, y1: i32, r: i32, argb: u32) {
        let r = r.max(0);
        let a = (argb >> 24) & 0xFF;
        if a == 0 { return; }

        let rf = r as f32;
        let x0f = x0 as f32;
        let y0f = y0 as f32;
        let x1f = x1 as f32;
        let y1f = y1 as f32;

        for y in y0..y1 {
            let py = y as f32 + 0.5;
            for x in x0..x1 {
                let px = x as f32 + 0.5;

                let cx = if px < x0f + rf {
                    x0f + rf
                } else if px >= x1f - rf {
                    x1f - rf
                } else {
                    px
                };

                let cy = if py < y0f + rf {
                    y0f + rf
                } else if py >= y1f - rf {
                    y1f - rf
                } else {
                    py
                };

                let dx = px - cx;
                let dy = py - cy;
                let dist = (dx * dx + dy * dy).sqrt();
                let coverage = (rf + 0.5 - dist).clamp(0.0, 1.0);

                if coverage > 0.0 {
                    if coverage >= 0.99 {
                        self.set_pixel(x, y, argb);
                    } else {
                        self.blend_pixel(x, y, argb, coverage);
                    }
                }
            }
        }
    }

    pub fn outline_rounded_rect(&mut self, x0: i32, y0: i32, x1: i32, y1: i32, r: i32, width: i32, argb: u32) {
        let wf = width.max(1) as f32;
        let rf = r as f32;
        let inner_r = (rf - wf).max(0.0);

        let x0f = x0 as f32;
        let y0f = y0 as f32;
        let x1f = x1 as f32;
        let y1f = y1 as f32;

        let in_x0 = x0f + wf;
        let in_y0 = y0f + wf;
        let in_x1 = x1f - wf;
        let in_y1 = y1f - wf;

        for y in y0..y1 {
            let py = y as f32 + 0.5;
            for x in x0..x1 {
                let px = x as f32 + 0.5;

                // Outer boundary coverage
                let cx_out = if px < x0f + rf {
                    x0f + rf
                } else if px >= x1f - rf {
                    x1f - rf
                } else {
                    px
                };
                let cy_out = if py < y0f + rf {
                    y0f + rf
                } else if py >= y1f - rf {
                    y1f - rf
                } else {
                    py
                };
                let d_out = ((px - cx_out).powi(2) + (py - cy_out).powi(2)).sqrt();
                let cov_out = (rf + 0.5 - d_out).clamp(0.0, 1.0);

                // Inner boundary coverage
                let cov_in = if px >= in_x0 && px <= in_x1 && py >= in_y0 && py <= in_y1 {
                    let cx_in = if px < in_x0 + inner_r {
                        in_x0 + inner_r
                    } else if px >= in_x1 - inner_r {
                        in_x1 - inner_r
                    } else {
                        px
                    };
                    let cy_in = if py < in_y0 + inner_r {
                        in_y0 + inner_r
                    } else if py >= in_y1 - inner_r {
                        in_y1 - inner_r
                    } else {
                        py
                    };
                    let d_in = ((px - cx_in).powi(2) + (py - cy_in).powi(2)).sqrt();
                    (inner_r + 0.5 - d_in).clamp(0.0, 1.0)
                } else {
                    0.0
                };

                let stroke_cov = (cov_out - cov_in).clamp(0.0, 1.0);
                if stroke_cov > 0.0 {
                    self.blend_pixel(x, y, argb, stroke_cov);
                }
            }
        }
    }

    pub fn draw_text(&mut self, text: &str, cx: i32, cy: i32, font_size: i32, color_rgb: u32, is_bold: bool) {
        unsafe {
            use windows::Win32::Graphics::Gdi::{
                CreateFontW, DrawTextW, SetBkMode, SetTextColor, DT_CENTER, DT_NOCLIP, DT_SINGLELINE,
                DT_VCENTER, FW_BOLD, FW_NORMAL, TRANSPARENT,
            };

            let font_name: Vec<u16> = "Segoe UI\0".encode_utf16().collect();
            let hfont = CreateFontW(
                font_size,
                0,
                0,
                0,
                if is_bold { FW_BOLD.0 as i32 } else { FW_NORMAL.0 as i32 },
                0,
                0,
                0,
                1, // DEFAULT_CHARSET
                0,
                0,
                5, // CLEARTYPE_QUALITY
                0,
                PCWSTR::from_raw(font_name.as_ptr()),
            );

            let old_font = SelectObject(self.hdc, hfont);
            let _ = SetBkMode(self.hdc, TRANSPARENT);
            let _ = SetTextColor(self.hdc, COLORREF(color_rgb));

            let text_u16: Vec<u16> = text.encode_utf16().collect();
            let mut rect = RECT {
                left: cx - 200,
                top: cy - 30,
                right: cx + 200,
                bottom: cy + 30,
            };

            let _ = DrawTextW(
                self.hdc,
                &mut text_u16.clone(),
                &mut rect,
                DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOCLIP,
            );

            let _ = SelectObject(self.hdc, old_font);
            let _ = DeleteObject(hfont);

            // GDI text drawing doesn't set the 32-bit alpha channel (it writes 0x00RRGGBB).
            // Fix alpha channel for non-black text pixels in the bounding box:
            let left = rect.left.max(0);
            let right = rect.right.min(self.width);
            let top = rect.top.max(0);
            let bottom = rect.bottom.min(self.height);

            for y in top..bottom {
                for x in left..right {
                    let idx = (y * self.width + x) as isize;
                    let p = *self.bits.offset(idx);
                    if (p & 0x00FFFFFF) != 0 {
                        *self.bits.offset(idx) = 0xFF000000 | (p & 0x00FFFFFF);
                    }
                }
            }
        }
    }

    pub fn draw_text_aligned(&mut self, text: &str, x: i32, y: i32, font_size: i32, color_rgb: u32, align_right: bool) {
        unsafe {
            use windows::Win32::Graphics::Gdi::{
                CreateFontW, DrawTextW, SetBkMode, SetTextColor, DT_LEFT, DT_NOCLIP, DT_RIGHT,
                DT_SINGLELINE, DT_VCENTER, FW_NORMAL, TRANSPARENT,
            };

            let font_name: Vec<u16> = "Segoe UI\0".encode_utf16().collect();
            let hfont = CreateFontW(
                font_size,
                0,
                0,
                0,
                FW_NORMAL.0 as i32,
                0,
                0,
                0,
                1,
                0,
                0,
                5,
                0,
                PCWSTR::from_raw(font_name.as_ptr()),
            );

            let old_font = SelectObject(self.hdc, hfont);
            let _ = SetBkMode(self.hdc, TRANSPARENT);
            let _ = SetTextColor(self.hdc, COLORREF(color_rgb));

            let text_u16: Vec<u16> = text.encode_utf16().collect();
            let mut rect = if align_right {
                RECT { left: x - 400, top: y - 20, right: x, bottom: y + 20 }
            } else {
                RECT { left: x, top: y - 20, right: x + 400, bottom: y + 20 }
            };

            let flag = if align_right { DT_RIGHT } else { DT_LEFT };
            let _ = DrawTextW(self.hdc, &mut text_u16.clone(), &mut rect, flag | DT_VCENTER | DT_SINGLELINE | DT_NOCLIP);

            let _ = SelectObject(self.hdc, old_font);
            let _ = DeleteObject(hfont);

            let left = rect.left.max(0);
            let right = rect.right.min(self.width);
            let top = rect.top.max(0);
            let bottom = rect.bottom.min(self.height);

            for cy in top..bottom {
                for cx in left..right {
                    let idx = (cy * self.width + cx) as isize;
                    let p = *self.bits.offset(idx);
                    if (p & 0x00FFFFFF) != 0 {
                        *self.bits.offset(idx) = 0xFF000000 | (p & 0x00FFFFFF);
                    }
                }
            }
        }
    }

    pub fn present_to_window(&self, hwnd: HWND, x: i32, y: i32) {
        unsafe {
            let screen_dc = GetDC(HWND(std::ptr::null_mut()));
            let mut pt_src = POINT { x: 0, y: 0 };
            let mut pt_dst = POINT { x, y };
            let mut size = SIZE {
                cx: self.width,
                cy: self.height,
            };
            let blend = BLENDFUNCTION {
                BlendOp: 0,
                BlendFlags: 0,
                SourceConstantAlpha: 255,
                AlphaFormat: 1, // AC_SRC_ALPHA
            };

            let _ = UpdateLayeredWindow(
                hwnd,
                screen_dc,
                Some(&mut pt_dst),
                Some(&mut size),
                self.hdc,
                Some(&mut pt_src),
                COLORREF(0),
                Some(&blend),
                ULW_ALPHA,
            );

            let _ = ReleaseDC(HWND(std::ptr::null_mut()), screen_dc);
        }
    }
}

impl Drop for BitmapBuffer {
    fn drop(&mut self) {
        unsafe {
            let _ = SelectObject(self.hdc, self.old_bmp);
            let _ = DeleteObject(self.hbmp);
            let _ = DeleteDC(self.hdc);
        }
    }
}

pub fn parse_hex_color(hex: &str) -> u32 {
    let s = hex.trim_start_matches('#');
    match s.len() {
        6 => {
            if let Ok(val) = u32::from_str_radix(s, 16) {
                0xFF000000 | ((val & 0xFF) << 16) | (val & 0xFF00) | ((val >> 16) & 0xFF)
            } else {
                0xFFFFFFFF
            }
        }
        8 => {
            if let Ok(val) = u32::from_str_radix(s, 16) {
                let r = (val >> 24) & 0xFF;
                let g = (val >> 16) & 0xFF;
                let b = (val >> 8) & 0xFF;
                let a = val & 0xFF;
                (a << 24) | (r << 16) | (g << 8) | b
            } else {
                0xFFFFFFFF
            }
        }
        _ => 0xFFFFFFFF,
    }
}
