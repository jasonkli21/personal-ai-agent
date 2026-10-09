"""Final local output guard for accidental credential echoes, including split deltas."""


class CredentialEcho(ValueError):
    def __init__(self):
        super().__init__("bridge_credential_echo")


class LocalOutputGuard:
    def __init__(self, protected_values: tuple[str, ...]):
        self.values = tuple(value for value in protected_values if value)
        self.pending = ""
        self.states = [0] * len(self.values)
        self.failures = []
        for value in self.values:
            failure = [0] * len(value)
            size = 0
            for index in range(1, len(value)):
                while size and value[index] != value[size]:
                    size = failure[size - 1]
                if value[index] == value[size]:
                    size += 1
                failure[index] = size
            self.failures.append(failure)

    def check(self, text: str):
        if any(value in text for value in self.values):
            raise CredentialEcho()

    def feed(self, text: str) -> str:
        combined = self.pending + text
        # Incremental KMP avoids quadratic prefix scanning for long JWTs.
        for index, value in enumerate(self.values):
            size = self.states[index]
            failure = self.failures[index]
            for character in text:
                while size and character != value[size]:
                    size = failure[size - 1]
                if character == value[size]:
                    size += 1
                    if size == len(value):
                        raise CredentialEcho()
            self.states[index] = size
        keep = max(self.states, default=0)
        self.pending = combined[-keep:] if keep else ""
        return combined[:-keep] if keep else combined

    def finish(self) -> str:
        self.check(self.pending)
        result, self.pending = self.pending, ""
        self.states = [0] * len(self.values)
        return result
