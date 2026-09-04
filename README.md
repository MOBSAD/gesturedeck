# GestureDeck

GestureDeck é um aplicativo simples para Linux que usa a webcam para controlar o volume do sistema. O MediaPipe detecta uma mão e a distância entre as pontas do polegar e do indicador define o volume. As mudanças são suavizadas antes de serem enviadas ao PipeWire com `wpctl`.

## Requisitos

- Linux com PipeWire e o comando `wpctl` disponível
- webcam acessível em `/dev/video0`
- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- ambiente gráfico para exibir a imagem da câmera

## Instalação

```bash
uv sync --python 3.12
```

## Execução

```bash
uv run python main.py
```

## Controles

- aproxime o polegar e o indicador para diminuir o volume;
- afaste os dedos para aumentar o volume;
- pressione `Q` ou `Esc` na janela da câmera para sair;
- pressione `Ctrl+C` no terminal para encerrar.

A câmera é liberada ao sair normalmente e também quando ocorre um erro.

## Testes

```bash
uv run python -m unittest discover -s tests -v
```

## Problemas comuns

- **A câmera não abre:** confira se `/dev/video0` existe, se seu usuário tem permissão e se outro programa não está usando a webcam.
- **O volume não muda:** execute `wpctl status` para confirmar que PipeWire/WirePlumber está ativo e que existe uma saída de áudio padrão.
- **A janela não aparece:** confirme que há uma sessão gráfica ativa.
- **A mão não é detectada:** use boa iluminação e mantenha a mão inteira visível.

## Licença

Distribuído sob a licença MIT. Consulte [LICENSE](LICENSE).
