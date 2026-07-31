
# SubtitleTranslator

## Configuração privada neste Mac

Adicione as suas credenciais de API ao macOS Keychain e escolha qualquer pasta de mídia. Então confirme as ferramentas da mídia. O aplicativo não tem conta, telemetria ou servidor operado pelo desenvolvedor.

1. Iniciar a configuração
2. Instalar Homebrew
3. Instalar Ferramentas Faltantes
4. Salvar as chaves da API para Keychain
5. Escolha um arquivo de mídia
6. Preparar Subtítulos
7. Aberto em mpv

```bash
brew install ffmpeg mkvtoolnix mpv
```

As alterações de idioma aplicam-se após a reinicialização do aplicativo.

As credenciais da API ficam no macOS Keychain . Processamento de subtítulos e arquivos de mídia permanecem neste Mac. A OpenAI só recebe textos subtítulos quando traduz. A OpenSubtitles só recebe metadados da pesquisa quando você faz uma pesquisa. As solicitações vão diretamente para esses fornecedores.

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
