
# SubtitleTranslator

## Thiết lập riêng tư trên Mac này

Thêm khóa API vào macOS Keychain và chọn bất kỳ thư mục media nào. Sau đó kiểm tra các công cụ đa phương tiện. Ứng dụng không có tài khoản, không thu thập dữ liệu đo từ xa và không sử dụng máy chủ do nhà phát triển vận hành.

1. Bắt đầu cài đặt
2. Lắp đặt Homebrew
3. Thiết lập các công cụ bị thiếu
4. Lưu khóa API vào Keychain
5. Chọn tệp media
6. Chuẩn bị phụ đề
7. Mở bằng mpv

```bash
brew install ffmpeg mkvtoolnix mpv
```

Thay đổi ngôn ngữ áp dụng sau khi khởi động lại ứng dụng.

Khóa API được lưu trong macOS Keychain. Việc xử lý phụ đề và các tập tin truyền thông vẫn ở trên Mac này. OpenAI chỉ nhận văn bản phụ đề khi bạn dịch. OpenSubtitles chỉ nhận được metadata tìm kiếm khi bạn tìm kiếm. Các yêu cầu đi trực tiếp đến các nhà cung cấp.

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
