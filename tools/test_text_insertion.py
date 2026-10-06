import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLineEdit

from georgian_dictation.insertion.windows import TextInserter


EXPECTED = "ქართული Unicode ტექსტი"


def main() -> int:
    app = QApplication([])
    edit = QLineEdit()
    edit.setWindowTitle("GeorgianDictation insertion integration test")
    edit.resize(520, 70)
    edit.show()
    edit.raise_()
    edit.activateWindow()
    edit.setFocus()
    inserter = TextInserter()
    result = {"ok": False}

    def insert() -> None:
        edit.activateWindow()
        edit.setFocus()
        inserter.insert(EXPECTED, "unicode")

    def verify() -> None:
        result["ok"] = edit.text() == EXPECTED
        print(f"received={edit.text()!r}")
        app.quit()

    QTimer.singleShot(350, insert)
    QTimer.singleShot(1000, verify)
    app.exec()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

