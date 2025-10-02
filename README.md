# OtonoDentatsu-PC

Windows GUI sender for streaming audio (microphone or system loopback) over UDP with Opus codec to the Android client.

Features:
- Tkinter GUI with tray icon
- Source selection: Microphone or System audio (WASAPI loopback)
- Opus encoding (APPLICATION_AUDIO)
- Decoupled audio pipeline: lightweight PortAudio callback + sender thread
- Optional L4S ECN marking (ECT(1))

Build (PyInstaller):
- Python 3.11+ recommended
- pip install -r requirements.txt
- pyinstaller --noconsole --windowed --onefile --name "OND Client" --icon icon.ico --add-data "icon.ico;." --add-data "icon.png;." server_gui.pyw

Run:
- Launch OND Client.exe (or `python server_gui.pyw` in dev)
- Set port and parameters, click Start

License: MIT (add your choice)
