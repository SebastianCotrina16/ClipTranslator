from __future__ import annotations

import getpass


class Console:
    def __init__(self, assume_defaults: bool = False) -> None:
        self.assume_defaults = assume_defaults

    def ask(self, prompt: str, default: str) -> str:
        if self.assume_defaults:
            print(f"{prompt} [{default}]: {default}")
            return default
        answer = input(f"{prompt} [{default}]: ").strip()
        return answer or default

    def ask_required(self, prompt: str, default: str = "") -> str:
        while True:
            answer = self.ask(prompt, default).strip()
            if answer:
                return answer
            if self.assume_defaults:
                return ""
            print("   Este dato es obligatorio.")

    def ask_secret(self, prompt: str) -> str:
        if self.assume_defaults:
            return ""
        return getpass.getpass(prompt).strip()

    def confirm(self, prompt: str, default: bool = True) -> bool:
        hint = "S/n" if default else "s/N"
        answer = self.ask(f"{prompt} ({hint})", "s" if default else "n").lower()
        return answer.startswith(("s", "y"))

    def choose(self, prompt: str, options: list[str], default_index: int) -> int:
        for number, option in enumerate(options, start=1):
            print(f"   [{number}] {option}")
        while True:
            answer = self.ask(prompt, str(default_index + 1))
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return int(answer) - 1
            print("   Opción no válida.")
