import unittest
from ui_style import ctk, UIStyle
from quota_slider import QuotaLimitBar


class QuotaSliderTests(unittest.TestCase):
    def test_hold_drag_tooltip_and_release_in_both_themes_and_scales(self):
        for theme in ('dark', 'light'):
            for scale in (.8, 1, 1.25):
                with self.subTest(theme=theme, scale=scale):
                    root = ctk.CTk()
                    try:
                        style = UIStyle(root, {'theme': theme})
                        ctk.set_widget_scaling(scale)
                        root.geometry('480x220')
                        row = ctk.CTkFrame(root, width=350, height=22)
                        row.place(x=40, y=90)
                        values = []
                        bar = QuotaLimitBar(row, floor=30, command=values.append)
                        bar.place(x=0, y=0, relwidth=1)
                        root.update()
                        before = (bar.marker.winfo_width(), bar.marker.winfo_height())
                        row_size = (row.winfo_width(), row.winfo_height())
                        bar.marker._canvas.event_generate('<ButtonPress-1>', x=2, y=2)
                        root.update()
                        self.assertTrue(bar.dragging)
                        self.assertGreater(bar.marker.winfo_width(), before[0]*1.8)
                        self.assertGreater(bar.marker.winfo_height(), before[1]*1.5)
                        self.assertTrue(bar.bubble.winfo_viewable())
                        old_x = bar.bubble.winfo_rootx()
                        # Send real Tk motion events with root coordinates, as a held pointer does.
                        for fraction in (.7, .4, 0, 1):
                            px = round(bar.winfo_rootx()+bar.winfo_width()*fraction)
                            bar.marker._canvas.event_generate('<B1-Motion>', rootx=px,
                                rooty=bar.winfo_rooty()+4, x=2, y=2)
                            root.update()
                            self.assertAlmostEqual(bar.floor, fraction*100, delta=1)
                            self.assertEqual(bar.bubble.cget('text'), f'{bar.floor}%')
                            self.assertTrue(bar.bubble.winfo_viewable())
                            self.assertLessEqual(bar.bubble.winfo_rooty()+bar.bubble.winfo_height(), bar.winfo_rooty())
                            center = bar.bubble.winfo_rootx()+bar.bubble.winfo_width()/2
                            handle = bar.marker.winfo_rootx()+bar.marker.winfo_width()/2
                            self.assertAlmostEqual(center, handle, delta=3)
                            if fraction == .7:
                                self.assertGreater(bar.bubble.winfo_rootx(), old_x)
                            self.assertEqual(row_size, (row.winfo_width(), row.winfo_height()))
                        bar.marker._canvas.event_generate('<ButtonRelease-1>', rootx=px,
                            rooty=bar.winfo_rooty()+4, x=2, y=2)
                        root.update()
                        self.assertFalse(bar.dragging)
                        self.assertFalse(bar.bubble.winfo_manager())
                        self.assertEqual(values, [100])
                        self.assertEqual(before, (bar.marker.winfo_width(), bar.marker.winfo_height()))
                        self.assertEqual(bar.marker.cget('fg_color'), style.color('#739aff'))
                    finally:
                        root.destroy()
        ctk.set_widget_scaling(1)
