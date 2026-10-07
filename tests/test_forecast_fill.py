import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App


class CanvasSpy:
    def __init__(self): self.rectangles = []; self.redraws = 0; self.lines = []
    def delete(self, *args): self.redraws += 1
    def winfo_width(self): return 426
    def configure(self, **kwargs): pass
    def create_rectangle(self, *args, **kwargs): self.rectangles.append((args, kwargs))
    def create_line(self, *args, **kwargs): self.lines.append((args, kwargs))
    def create_text(self, *args, **kwargs): pass


class ForecastFillTests(unittest.TestCase):
    def test_fill_is_actual_percentage_even_with_time_forecasts(self):
        for remaining in (.287, .5, 1, 0):
            canvas = CanvasSpy()
            view = SimpleNamespace(forecast_canvas=canvas,
                sidebar=SimpleNamespace(_get_widget_scaling=lambda: 1),
                forecast_font=SimpleNamespace(measure=lambda s: 60, metrics=lambda s: 15),
                total_remaining=remaining, quota_color=App.quota_color,
                total_forecast=[{'reset': (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), 'remaining': .8}])
            App.draw_total_forecast(view)
            App.draw_total_forecast(view)
            self.assertEqual(canvas.redraws, 1)
            marks = [coords for coords, attrs in canvas.rectangles if attrs.get('tags') == 'forecast_time']
            self.assertAlmostEqual(((marks[0][0] + marks[0][2]) / 2 - 3) / 420, .8)
            self.assertTrue(all('dash' not in attrs for _, attrs in canvas.rectangles))
            fills = [coords for coords, attrs in canvas.rectangles if attrs.get('tags') == 'quota_remaining']
            if remaining:
                self.assertEqual(len(fills), 1)
                self.assertAlmostEqual((fills[0][2] - fills[0][0]) / 420, remaining)
            else:
                self.assertEqual(fills, [])
            weekly_canvas = CanvasSpy()
            view.weekly_forecast_canvas = weekly_canvas
            view.total_weekly_remaining = .55
            view.total_weekly_forecast = [{'reset': (datetime.now(timezone.utc) + timedelta(days=4)).isoformat(), 'remaining': .75}]
            App.draw_total_forecast(view, weekly=True)
            weekly_fill = next(coords for coords, attrs in weekly_canvas.rectangles if attrs.get('tags') == 'quota_remaining')
            weekly_mark = next(coords for coords, attrs in weekly_canvas.rectangles if attrs.get('tags') == 'forecast_time')
            self.assertAlmostEqual((weekly_fill[2] - weekly_fill[0]) / 420, .55)
            self.assertAlmostEqual(((weekly_mark[0] + weekly_mark[2]) / 2 - 3) / 420, .75)
            self.assertEqual(canvas.redraws, 1)


if __name__ == '__main__': unittest.main()
