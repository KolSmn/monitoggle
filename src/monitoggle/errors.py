from __future__ import annotations


class UserError(Exception):
    """A failure to report to the user; the CLI logs it and exits with 1.

    Takes a %-style template and its arguments like a logging call, and keeps
    them apart, so front-ends (the GUI) can translate the template and log
    files stay in English.
    """

    def __init__(self, template: str, *args: object) -> None:
        super().__init__(template % args if args else template)
        self.template = template
        self.template_args = args
