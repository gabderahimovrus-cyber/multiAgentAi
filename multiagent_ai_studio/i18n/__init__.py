from .ru import STRINGS

class Translator:
    def __init__(self, language: str = "ru") -> None:
        self.language = language
        self._catalogs = {"ru": STRINGS}

    def t(self, key: str, **kwargs) -> str:
        value = self._catalogs.get(self.language, STRINGS).get(key, key)
        return value.format(**kwargs) if kwargs else value
