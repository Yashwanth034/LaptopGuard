from __future__ import annotations

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk, Gtk

window = Gtk.Window()
window.set_decorated(False)
window.set_keep_above(True)
window.fullscreen()
provider = Gtk.CssProvider()
provider.load_from_data(b'window { background: #ffffff; }')
screen = Gdk.Screen.get_default()
if screen is not None:
    Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
window.connect('destroy', Gtk.main_quit)
window.show_all()
Gtk.main()
