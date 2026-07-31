
# SubtitleTranslator

## 이 Mac에 개인 설정

macOS Keychain에 API 인증서를 추가하고 모든 미디어 폴더를 선택하십시오. 그럼 미디어 도구를 확인해 주세요. 앱에는 계정, 텔레메트리, 개발자가 운영하는 서버가 없습니다.

1. 설정 시작
2. Homebrew를 설치
3. 실종 된 도구 를 설치
4. Keychain에 API 키를 저장합니다
5. 미디어 파일을 선택
6. 자막을 준비하라
7. mpv에서 열립니다

```bash
brew install ffmpeg mkvtoolnix mpv
```

응용 프로그램을 다시 시작하면 언어 변경이 적용됩니다.

API 자격증은 macOS Keychain에서 유지됩니다 . 자막 처리 및 미디어 파일은 이 맥에 남아 있습니다. OpenAI는 당신이 번역할 때만 자막 텍스트를 수신합니다. OpenSubtitles는 검색을 할 때만 검색 메타데이터를 수신합니다. 요청은 바로 그 공급자에게 전달됩니다.

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
