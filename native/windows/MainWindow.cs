using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Threading;

namespace Omni;
public sealed class MainWindow : Window
{
    readonly bool demo;
    readonly Bridge? bridge;
    readonly Grid layout = new();
    readonly StackPanel sidebar = new();
    readonly StackPanel groups = new();
    readonly StackPanel footer = new();
    readonly Grid content = new();
    readonly StackPanel details = new();
    readonly StackPanel settings = new();
    readonly TextBlock notice = new();
    readonly Dictionary<string, ServiceView> services = new();
    readonly Dictionary<string, AccountView> accounts = new();
    readonly Dictionary<string, CheckBox> checks = new();
    readonly ComboBox themeChoice = new() { Width=160, HorizontalAlignment=HorizontalAlignment.Left };
    readonly ComboBox languageChoice = new() { Width=160, HorizontalAlignment=HorizontalAlignment.Left };
    readonly Dictionary<string,bool> visible = new();
    bool applying, privateNames, russian, settingsOpen;
    readonly DispatcherTimer timer = new() { Interval=TimeSpan.FromSeconds(60) };
    public static readonly string[] Providers = ["gemini","openai","claude","grok","tokenharbor"];
    public static string TitleFor(string provider) => provider switch {
        "gemini" => "Google Gemini", "openai" => "OpenAI", "claude" => "Claude", "grok" => "Grok", _ => "TokenHarbor"
    };
    public string Text(string en, string ru) => russian ? ru : en;
    public MainWindow(bool demoMode)
    {
        demo=demoMode; Title="Omni"; Width=1120; Height=780; MinWidth=680; MinHeight=540;
        FontFamily=new FontFamily("Segoe UI"); FontSize=12;
        SetResourceReference(BackgroundProperty,"Background");
        layout.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(300) });
        layout.ColumnDefinitions.Add(new ColumnDefinition());
        Content=layout;
        var sideGrid=new Grid(); sideGrid.SetResourceReference(BackgroundProperty,"Panel");
        sideGrid.RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
        sideGrid.RowDefinitions.Add(new RowDefinition());
        sideGrid.RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
        layout.Children.Add(sideGrid);
        var header=new StackPanel { Margin=new Thickness(12,8,12,4) }; sideGrid.Children.Add(header);
        var titleRow=new DockPanel(); header.Children.Add(titleRow);
        var gear=Button("⚙",(_,_)=>ToggleSettings()); gear.Width=34; DockPanel.SetDock(gear,Dock.Right); titleRow.Children.Add(gear);
        var privacy=Button("◉",async (_,_)=>await Action("private",new {value=!privateNames}));
        privacy.ToolTip="Hide account names"; DockPanel.SetDock(privacy,Dock.Right); titleRow.Children.Add(privacy);
        titleRow.Children.Add(Label("Omni",23,true));
        var add=new WrapPanel(); header.Children.Add(add);
        foreach(var provider in Providers)
        {
            visible[provider]=true;
            var button=Button("+ "+TitleFor(provider),(_,_)=>LoginMenu(provider));
            button.FontSize=11; button.Tag=provider; add.Children.Add(button);
            services[provider]=new ServiceView(this,provider,button);
            groups.Children.Add(services[provider].Root);
            footer.Children.Add(services[provider].Summary);
        }
        var scroll=new ScrollViewer { Content=groups, VerticalScrollBarVisibility=ScrollBarVisibility.Auto,
                                      HorizontalScrollBarVisibility=ScrollBarVisibility.Disabled };
        Grid.SetRow(scroll,1); sideGrid.Children.Add(scroll);
        footer.Margin=new Thickness(12,4,12,8); Grid.SetRow(footer,2); sideGrid.Children.Add(footer);
        content.Margin=new Thickness(24,18,24,12); Grid.SetColumn(content,1); layout.Children.Add(content);
        var detailsScroll=new ScrollViewer { Content=details, VerticalScrollBarVisibility=ScrollBarVisibility.Auto };
        var settingsScroll=new ScrollViewer { Content=settings, VerticalScrollBarVisibility=ScrollBarVisibility.Auto,
                                              Visibility=Visibility.Collapsed };
        detailsScroll.Name="Details"; settingsScroll.Name="Settings";
        content.Children.Add(detailsScroll); content.Children.Add(settingsScroll);
        details.Children.Add(Label("Saved accounts",28,true));
        var route=Button("Automatic routing",async (_,_)=>await Action("route")); route.HorizontalAlignment=HorizontalAlignment.Left;
        details.Children.Add(route);
        details.Children.Add(Label("Select an account to see its quota and actions.",13));
        details.Children.Add(notice);
        settings.Children.Add(Label("Display settings",24,true));
        foreach(var provider in Providers)
        {
            var check=new CheckBox { Content=TitleFor(provider), IsChecked=true, Tag=provider };
            check.Checked+=VisibilityChanged; check.Unchecked+=VisibilityChanged;
            checks[provider]=check; settings.Children.Add(check);
        }
        settings.Children.Add(Label("Theme",16,true)); themeChoice.ItemsSource=new[]{"Dark","Light"};
        themeChoice.SelectedIndex=0; themeChoice.SelectionChanged+=async (_,_)=>{
            if(!applying) await Action("theme",new {value=themeChoice.SelectedIndex==1 ? "light":"dark"});
        }; settings.Children.Add(themeChoice);
        settings.Children.Add(Label("Language",16,true)); languageChoice.ItemsSource=new[]{"English","Русский"};
        languageChoice.SelectedIndex=0; languageChoice.SelectionChanged+=async (_,_)=>{
            if(!applying) await Action("language",new {value=languageChoice.SelectedIndex==1 ? "ru":"en"});
        }; settings.Children.Add(languageChoice);
        settings.Children.Add(Button("GitHub ↗",(_,_)=>Open("https://github.com/nikitaeight24family/Omni/releases/latest")));
        Loaded+=(_,_)=>{
            if(demo) LoadDemo(); else {bridge!.Start(); timer.Start();}
            if(Environment.GetCommandLineArgs().Contains("--self-test")) Dispatcher.BeginInvoke(SelfTest,DispatcherPriority.ApplicationIdle);
        };
        if(!demo)
        {
            var root=FindRoot(); bridge=new Bridge(root);
            bridge.Message+=message=>Dispatcher.BeginInvoke(()=>Receive(message));
        }
        timer.Tick+=async (_,_)=>await Action("refresh");
        Closed+=(_,_)=>{timer.Stop();bridge?.Dispose();};
    }
    static string FindRoot()
    {
        var configured=Environment.GetEnvironmentVariable("OMNI_SOURCE_ROOT");
        if(configured!=null)return configured;
        for(var directory=new DirectoryInfo(AppContext.BaseDirectory);directory!=null;directory=directory.Parent)
            if(File.Exists(Path.Combine(directory.FullName,"native_bridge.py")))return directory.FullName;
        return AppContext.BaseDirectory;
    }
    public static Button Button(string title, RoutedEventHandler handler)
    {var b=new Button{Content=title};b.Click+=handler;return b;}
    public static TextBlock Label(string text,double size=12,bool bold=false)
        =>new(){Text=text,FontSize=size,FontWeight=bold?FontWeights.SemiBold:FontWeights.Normal,Margin=new Thickness(0,4,0,6)};
    public static void Open(string url)=>Process.Start(new ProcessStartInfo(url){UseShellExecute=true});
    public void ToggleSettings()
    {
        settingsOpen=!settingsOpen;
        content.Children[0].Visibility=settingsOpen?Visibility.Collapsed:Visibility.Visible;
        content.Children[1].Visibility=settingsOpen?Visibility.Visible:Visibility.Collapsed;
    }
    async void VisibilityChanged(object sender,RoutedEventArgs e)
    {
        if(applying)return;
        var check=(CheckBox)sender; var provider=(string)check.Tag;
        ApplyVisibility(provider,check.IsChecked==true);
        await Action("visibility",new {provider,value=check.IsChecked==true});
    }
    void ApplyVisibility(string provider,bool value)
    {
        visible[provider]=value;
        services[provider].Root.Visibility=services[provider].Summary.Visibility=
            services[provider].Add.Visibility=value?Visibility.Visible:Visibility.Collapsed;
    }
    public async Task<JsonElement?> Action(string action,object? fields=null)
    {
        if(demo)return null;
        try{return await bridge!.Send(action,fields);}
        catch(Exception error){notice.Text=error.Message;return null;}
    }
    public void RenameAccount(string id)
    {
        var panel=new StackPanel{Margin=new Thickness(18)};
        panel.Children.Add(Label(Text("New account name","Новое название аккаунта"),17,true));
        var entry=new TextBox{MaxLength=120};panel.Children.Add(entry);
        var dialog=new Window{Title="Omni",Owner=this,Content=panel,Width=380,Height=180,
                              ResizeMode=ResizeMode.NoResize,WindowStartupLocation=WindowStartupLocation.CenterOwner};
        dialog.SetResourceReference(BackgroundProperty,"Background");
        panel.Children.Add(Button(Text("Save","Сохранить"),async (_,_)=>{
            await Action("rename",new{id,label=entry.Text});dialog.Close();
        }));dialog.ShowDialog();
    }
    void Receive(JsonElement message)
    {
        if(!message.TryGetProperty("event",out var ev))return;
        switch(ev.GetString())
        {
            case "preferences": ApplyPreferences(message.GetProperty("preferences"));break;
            case "account": UpdateAccount(message.GetProperty("account"));break;
            case "accounts":
                var ids=message.GetProperty("ids").EnumerateArray().Select(x=>x.GetString()!).ToHashSet();
                foreach(var id in accounts.Keys.Where(id=>!ids.Contains(id)).ToArray())
                {services[accounts[id].Provider].Remove(accounts[id]);accounts.Remove(id);}break;
            case "error":case "notice":notice.Text=message.GetProperty("message").GetString();break;
        }
    }
    void ApplyPreferences(JsonElement prefs)
    {
        applying=true;
        privateNames=prefs.GetProperty("private").GetBoolean(); russian=prefs.GetProperty("language").GetString()=="ru";
        var light=prefs.GetProperty("theme").GetString()=="light";
        var palette=new Dictionary<string,string> {{"Background",light?"#f4f6fa":"#10141d"},{"Panel",light?"#ffffff":"#191f2b"},
            {"Card",light?"#eaf0f8":"#222a38"},{"Foreground",light?"#1b2638":"#edf2fa"},{"Muted",light?"#52647b":"#9daec4"}};
        foreach(var (key,color) in palette)Application.Current.Resources[key]=new SolidColorBrush((Color)ColorConverter.ConvertFromString(color));
        foreach(var provider in Providers)
        {
            var show=prefs.GetProperty("visible").GetProperty(provider).GetBoolean();
            checks[provider].IsChecked=show;ApplyVisibility(provider,show);
        }
        themeChoice.SelectedIndex=light?1:0;languageChoice.SelectedIndex=russian?1:0;
        foreach(var account in accounts.Values)account.SetPrivacy(privateNames);
        applying=false;
    }
    void UpdateAccount(JsonElement data)
    {
        var id=data.GetProperty("id").GetString()!;var provider=data.GetProperty("provider").GetString()!;
        if(!accounts.TryGetValue(id,out var view))
        {
            view=new AccountView(this,id,provider);accounts[id]=view;services[provider].Insert(view);
        }
        view.Update(data,privateNames);services[provider].Refresh();
    }
    void LoginMenu(string provider)
    {
        var menu=new ContextMenu();
        var oauth=new MenuItem{Header=Text("Sign in","Войти через аккаунт")};
        oauth.Click+=async (_,_)=>{
            if(provider=="tokenharbor"){ApiDialog(provider);return;}
            var result=await Action("login",new{provider});if(result is not {} login)return;
            Open(login.GetProperty("url").GetString()!);
            if(login.TryGetProperty("user_code",out var code))notice.Text=code.GetString();
            var state=login.GetProperty("state").GetString();
            for(var n=0;n<450;n++)
            {
                await Task.Delay(2000);var response=await Action("login_status",new{state});
                if(response is not {} status)break;
                var value=status.GetProperty("status").GetString();
                if(value=="ok"){await Action("refresh");notice.Text=Text("Account added","Аккаунт добавлен");break;}
                if(value=="error"){notice.Text=status.TryGetProperty("error",out var error)?error.GetString():Text("Sign-in failed","Вход не выполнен");break;}
            }
        };menu.Items.Add(oauth);
        var api=new MenuItem{Header=Text("API key","API-ключ")};api.Click+=(_,_)=>ApiDialog(provider);menu.Items.Add(api);
        if(provider=="openai")
        {
            var import=new MenuItem{Header="auth.json"};import.Click+=async (_,_)=>{
                var file=new Microsoft.Win32.OpenFileDialog{Filter="JSON|*.json"};
                if(file.ShowDialog(this)==true)await Action("import",new{path=file.FileName});
            };menu.Items.Add(import);
        }
        menu.IsOpen=true;
    }
    void ApiDialog(string provider)
    {
        var panel=new StackPanel{Margin=new Thickness(18)};
        panel.Children.Add(Label(TitleFor(provider)+" · API",20,true));
        var name=new TextBox{Margin=new Thickness(0,5,0,5)};panel.Children.Add(name);
        var key=new PasswordBox{Margin=new Thickness(0,5,0,5)};panel.Children.Add(key);
        var window=new Window{Title="Omni",Owner=this,Content=panel,Width=400,Height=230,ResizeMode=ResizeMode.NoResize,
                              WindowStartupLocation=WindowStartupLocation.CenterOwner};window.SetResourceReference(BackgroundProperty,"Background");
        panel.Children.Add(Button(Text("Connect","Подключить"),async (_,_)=>{
            await Action("api",new{provider=TitleFor(provider) switch{"Google Gemini"=>"Gemini",_=>TitleFor(provider)},key=key.Password,label=name.Text});
            key.Clear();window.Close();
        }));window.ShowDialog();
    }
    void LoadDemo()
    {
        for(var index=0;index<12;index++)
        {
            var provider=index<8?"gemini":"openai";
            using var doc=JsonDocument.Parse(JsonSerializer.Serialize(new{id="demo"+index,provider,label="Account "+(index+1),
                plan=provider=="gemini"?"AI Pro":"Plus",status="Available",priority=index==0?3:0,disabled=false,
                windows=new[]{new{id="gemini/5h",label="5h",family="gemini",remaining=81-index*5,floor=0},
                              new{id="claude/weekly",label="1w",family="claude",remaining=51-index*2,floor=0}}}));
            UpdateAccount(doc.RootElement);
        }
    }
    void SelfTest()
    {
        var before=new Rect(Left,Top,Width,Height);
        ToggleSettings();ToggleSettings();
        if(settingsOpen||before!=new Rect(Left,Top,Width,Height))throw new Exception("Settings changed window geometry");
        foreach(var provider in Providers)
        {ApplyVisibility(provider,false);if(services[provider].Add.Visibility!=Visibility.Collapsed)throw new Exception("Service add button visible");ApplyVisibility(provider,true);}
        var view=accounts.Values.First();var original=view.Root;
        for(var n=0;n<100;n++)view.QuotaViews.Values.First().SetRemaining(n);
        if(original!=view.Root)throw new Exception("Card recreated");
        File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"native-self-test.json"),JsonSerializer.Serialize(new{settingsGeometry=true,visibility=true,retainedCard=true,toolkit="WPF"}));
        Close();
    }
}

public sealed class ServiceView
{
    readonly MainWindow window;
    public readonly StackPanel Root=new(){Margin=new Thickness(12,3,12,3)};
    public readonly StackPanel Body=new();
    public readonly Button Add;
    public readonly Button Summary;
    readonly Button header;
    readonly StackPanel dots=new(){Orientation=Orientation.Horizontal};
    readonly TextBlock title=new(){FontWeight=FontWeights.SemiBold,VerticalAlignment=VerticalAlignment.Center};
    readonly List<AccountView> accounts=[];
    readonly string provider;
    bool collapsed;
    public ServiceView(MainWindow window,string provider,Button add)
    {
        this.window=window;this.provider=provider;Add=add;
        var line=new DockPanel();DockPanel.SetDock(dots,Dock.Right);line.Children.Add(dots);line.Children.Add(title);
        header=MainWindow.Button("",(_,_)=>{collapsed=!collapsed;Body.Visibility=collapsed?Visibility.Collapsed:Visibility.Visible;Refresh();});
        header.Content=line;header.HorizontalContentAlignment=HorizontalAlignment.Stretch;Root.Children.Add(header);Root.Children.Add(Body);
        Summary=MainWindow.Button(Title(),(_,_)=>{collapsed=!collapsed;Body.Visibility=collapsed?Visibility.Collapsed:Visibility.Visible;Refresh();});
        Refresh();
    }
    string Title()=>MainWindow.TitleFor(provider)+" · "+accounts.Count+"pcs";
    public void Insert(AccountView view){accounts.Add(view);Body.Children.Add(view.Root);}
    public void Remove(AccountView view){accounts.Remove(view);Body.Children.Remove(view.Root);Refresh();}
    public void Refresh()
    {
        title.Text=(collapsed?"▸ ":"▾ ")+Title();Summary.Content=Title();
        var sorted=accounts.OrderByDescending(x=>x.Priority).ThenBy(x=>x.Id).ToArray();
        for(var index=0;index<sorted.Length;index++)
            if(Body.Children[index]!=sorted[index].Root){Body.Children.Remove(sorted[index].Root);Body.Children.Insert(index,sorted[index].Root);}
        dots.Children.Clear();
        if(collapsed)
            foreach(var label in new[]{"5h","1w"})
            {
                var values=accounts.SelectMany(x=>x.QuotaViews.Values).Where(x=>x.Label==label&&x.Remaining.HasValue).Select(x=>x.Remaining!.Value).ToArray();
                var value=values.Length>0?values.Average():(double?)null;
                var circle=new Border{CornerRadius=new CornerRadius(14),BorderThickness=new Thickness(1),Width=25,Height=25,Margin=new Thickness(2,0,0,0),
                    BorderBrush=QuotaView.ColorFor(value),Child=new TextBlock{Text=label,FontSize=9,HorizontalAlignment=HorizontalAlignment.Center,VerticalAlignment=VerticalAlignment.Center}};
                dots.Children.Add(circle);
            }
    }
}
public sealed class AccountView
{
    readonly MainWindow window;
    public string Id {get;}
    public string Provider {get;}
    public int Priority {get;private set;}
    public readonly Border Root=new(){CornerRadius=new CornerRadius(9),BorderThickness=new Thickness(1),BorderBrush=new SolidColorBrush(Color.FromRgb(52,65,85)),Margin=new Thickness(0,2,0,2),Padding=new Thickness(8,5,8,5)};
    readonly StackPanel body=new();
    readonly TextBlock heading=MainWindow.Label("",12);
    readonly TextBlock plan=MainWindow.Label("",10,true);
    readonly TextBlock status=MainWindow.Label("",10);
    readonly TextBlock priority=MainWindow.Label("0",10);
    readonly Button pause;
    readonly Button reset;
    bool disabled;
    string name="";
    public readonly Dictionary<string,QuotaView> QuotaViews=new();
    public AccountView(MainWindow window,string id,string provider)
    {
        this.window=window;Id=id;Provider=provider;Root.SetResourceReference(Border.BackgroundProperty,"Card");Root.Child=body;
        var row=new DockPanel();body.Children.Add(row);pause=MainWindow.Button("⏸",async (_,_)=>await window.Action("pause",new{id}));
        heading.Cursor=System.Windows.Input.Cursors.Hand;
        heading.ToolTip=window.Text("Rename account","Переименовать аккаунт");
        heading.MouseLeftButtonUp+=(_,_)=>window.RenameAccount(id);
        pause.Padding=new Thickness(4,0,4,0);DockPanel.SetDock(pause,Dock.Right);row.Children.Add(pause);row.Children.Add(heading);
        var second=new DockPanel();body.Children.Add(second);
        var controls=new StackPanel{Orientation=Orientation.Horizontal};DockPanel.SetDock(controls,Dock.Right);second.Children.Add(controls);
        controls.Children.Add(MainWindow.Button("↓",async (_,_)=>await window.Action("priority",new{id,delta=-1})));controls.Children.Add(priority);
        controls.Children.Add(MainWindow.Button("↑",async (_,_)=>await window.Action("priority",new{id,delta=1})));
        second.Children.Add(plan);second.Children.Add(status);
        reset=MainWindow.Button(window.Text("Reset usage","Сбросить лимиты"),async (_,_)=>{
            if(MessageBox.Show(window,window.Text("Use one reset credit for this account?","Использовать один сброс для этого аккаунта?"),"Omni",MessageBoxButton.YesNo)==MessageBoxResult.Yes)
                await window.Action("reset",new{id});
        });reset.Visibility=Visibility.Collapsed;body.Children.Add(reset);
    }
    public void SetPrivacy(bool hide)=>heading.Text=hide?MainWindow.TitleFor(Provider)+" "+Id.GetHashCode().ToString("X")[..4]:name;
    public void Update(JsonElement data,bool hide)
    {
        name=data.GetProperty("label").GetString()!;SetPrivacy(hide);
        plan.Text=data.GetProperty("plan").GetString()+"  ";status.Text=data.GetProperty("status").GetString();
        Priority=data.GetProperty("priority").GetInt32();priority.Text=Priority.ToString();
        disabled=data.GetProperty("disabled").GetBoolean();pause.Content=disabled?"▶":"⏸";
        var credits=data.TryGetProperty("resetCredits",out var rc)&&rc.ValueKind==JsonValueKind.Number?rc.GetInt32():0;
        var available=data.TryGetProperty("resetAvailable",out var ra)&&ra.GetBoolean();
        reset.Visibility=credits>0||available?Visibility.Visible:Visibility.Collapsed;
        reset.IsEnabled=available&&!disabled;
        reset.ToolTip=available?window.Text("Use one reset credit","Использовать один сброс"):window.Text("OpenAI does not allow this reset right now","OpenAI сейчас не разрешает этот сброс");
        pause.ToolTip=window.Text(disabled?"Resume account":"Pause account",disabled?"Возобновить аккаунт":"Приостановить аккаунт");
        var active=data.TryGetProperty("active",out var a)&&a.GetBoolean();Root.BorderBrush=active?Brushes.MediumAquamarine:new SolidColorBrush(Color.FromRgb(52,65,85));
        foreach(var quota in data.GetProperty("windows").EnumerateArray())
        {
            var key=quota.GetProperty("id").GetString()!;
            if(!QuotaViews.TryGetValue(key,out var view)){view=new QuotaView(window,Id,key,quota.GetProperty("label").GetString()!);QuotaViews[key]=view;body.Children.Add(view.Root);}
            view.Update(quota);
        }
    }
}
public sealed class QuotaView
{
    public readonly Grid Root=new(){Margin=new Thickness(0,3,0,3)};
    readonly TextBlock text=new(){FontSize=10,VerticalAlignment=VerticalAlignment.Center};
    readonly ProgressBar progress=new(){Height=4,Minimum=0,Maximum=100};
    readonly Slider slider=new(){Minimum=0,Maximum=100,IsSnapToTickEnabled=true,TickFrequency=1,Height=18,AutoToolTipPlacement=AutoToolTipPlacement.TopLeft,AutoToolTipPrecision=0};
    bool applying;
    public string Label {get;}
    public double? Remaining {get;private set;}
    public QuotaView(MainWindow window,string account,string key,string label)
    {
        Label=label;Root.ColumnDefinitions.Add(new ColumnDefinition{Width=new GridLength(74)});Root.ColumnDefinitions.Add(new ColumnDefinition());
        Root.Children.Add(text);var track=new Grid();Grid.SetColumn(track,1);Root.Children.Add(track);track.Children.Add(progress);track.Children.Add(slider);
        slider.Template=(ControlTemplate)System.Windows.Markup.XamlReader.Parse("""
        <ControlTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" TargetType="Slider">
         <Grid><Track x:Name="PART_Track"><Track.DecreaseRepeatButton><RepeatButton Command="Slider.DecreaseLarge" Opacity="0"/></Track.DecreaseRepeatButton>
          <Track.Thumb><Thumb Width="4" Height="10" Background="#739aff"><Thumb.Template><ControlTemplate TargetType="Thumb">
           <Border x:Name="Handle" Background="{TemplateBinding Background}" BorderBrush="White" BorderThickness="1" CornerRadius="2"/>
           <ControlTemplate.Triggers><Trigger Property="IsDragging" Value="True"><Setter Property="Width" Value="10"/><Setter Property="Height" Value="16"/></Trigger></ControlTemplate.Triggers>
          </ControlTemplate></Thumb.Template></Thumb></Track.Thumb>
          <Track.IncreaseRepeatButton><RepeatButton Command="Slider.IncreaseLarge" Opacity="0"/></Track.IncreaseRepeatButton></Track></Grid>
        </ControlTemplate>
        """);
        slider.AddHandler(Thumb.DragCompletedEvent,new DragCompletedEventHandler(async (_,_)=>{
            if(!applying)await window.Action("floor",new{id=account,window=key,value=(int)slider.Value});
        }));
    }
    public static Brush ColorFor(double? value)=>value==null?Brushes.Gray:value<=0?Brushes.IndianRed:value<35?Brushes.Orange:Brushes.MediumAquamarine;
    public void SetRemaining(double? value)
    {Remaining=value;progress.Value=value??0;progress.Foreground=ColorFor(value);text.Foreground=ColorFor(value);text.Text=Label+" · "+(value.HasValue?$"{value:0}%":"—");}
    public void Update(JsonElement data)
    {applying=true;SetRemaining(data.GetProperty("remaining").ValueKind==JsonValueKind.Null?null:data.GetProperty("remaining").GetDouble());slider.Value=data.GetProperty("floor").GetDouble();applying=false;}
}
