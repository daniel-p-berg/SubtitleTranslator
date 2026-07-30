# Third-Party Notices

SubtitleTranslator is distributed under the MIT License. Binary releases also
contain open-source software under other licenses.

## Qt for Python

Binary releases include Qt, PySide6 Essentials, and Shiboken6. These components
are provided by The Qt Company under the GNU Lesser General Public License
version 3, the GNU General Public License, or a commercial Qt license.
SubtitleTranslator uses the LGPL option.

The Qt libraries remain dynamically linked inside the macOS application bundle.
SubtitleTranslator does not apply technical restrictions that prevent replacing
those libraries with interface-compatible versions for debugging modifications.
The application source and build instructions are available in this repository.

- [Qt for Python](https://doc.qt.io/qtforpython-6/)
- [Qt source code](https://code.qt.io/cgit/)
- [GNU LGPL version 3](https://www.gnu.org/licenses/lgpl-3.0.html)
- [GNU GPL version 3](https://www.gnu.org/licenses/gpl-3.0.html)

Copies of the LGPL and GPL are included in the `licenses` directory of each
binary release.

## Python Runtime and Packages

Binary releases include the Python runtime and Python packages used by the
application. Their copyright notices and license declarations are included in
`licenses/PYTHON-PACKAGES.txt`. The Python Software Foundation license is
included in `licenses/PYTHON-LICENSE.txt`.

Direct runtime dependencies include:

- keyring, MIT License
- Send2Trash, BSD License

The build is produced with PyInstaller under its GPL license and bootloader
exception.

## External Tools and Services

FFmpeg, FFprobe, MKVToolNix, and mpv are not bundled with SubtitleTranslator.
They are installed separately by the user and remain subject to their own
licenses. OpenAI and OpenSubtitles are external services subject to their own
terms and privacy policies.
