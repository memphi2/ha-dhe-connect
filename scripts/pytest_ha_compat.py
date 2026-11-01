"""Import HA before pytest plugins can import libraries it must alias."""

import homeassistant  # noqa: F401
