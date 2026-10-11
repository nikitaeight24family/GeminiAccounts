using System.Windows;
namespace Omni;
public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        DispatcherUnhandledException += (_, error) => {
            System.IO.File.WriteAllText(System.IO.Path.Combine(AppContext.BaseDirectory,"native-error.log"),error.Exception.ToString());
        };
        var window = new MainWindow(e.Args.Contains("--demo"));
        MainWindow = window;
        window.Show();
    }
}
