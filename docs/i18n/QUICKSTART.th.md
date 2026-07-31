
# SubtitleTranslator

## การตั้งค่าส่วนตัวบน Mac นี้

เพิ่มข้อมูล API ของคุณไปยัง macOS Keychain และเลือกโฟลเดอร์สื่อใดก็ได้ แล้วยืนยันเครื่องมือสื่อ แอพนั้นไม่มีบัญชี เทเลเมตร หรือเซอร์เวอร์ที่ผู้ประกอบการใช้งาน

1. เริ่มตั้ง
2. ติดตั้ง Homebrew
3. ติดตั้งเครื่องมือที่หายไป
4. เก็บกุญแจ API ไปยัง Keychain
5. เลือกไฟล์สื่อ
6. เตรียมคําบรรยาย
7. เปิดใน mpv

```bash
brew install ffmpeg mkvtoolnix mpv
```

การเปลี่ยนแปลงภาษาจะใช้หลังจากเปิดแอพใหม่

เอกสารฐาน API อยู่ที่ macOS Keychain การแปรรูปคําบรรยายและไฟล์สื่ออยู่บน Mac นี้ OpenAI จะรับข้อความรองคําแปลเมื่อคุณแปล OpenSubtitles ได้รับเมทาข้อมูลการค้นหาเท่านั้น เมื่อคุณค้นหา การขอไปตรงไปยังผู้ให้บริการเหล่านั้น

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
