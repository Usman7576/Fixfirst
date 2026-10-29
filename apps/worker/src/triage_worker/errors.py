class PermanentJobError(Exception):
    """Retrying won't help. The message is shown to users as the scan's failure reason."""


class TransientJobError(Exception):
    """Worth retrying later (network blips, GitHub hiccups)."""
