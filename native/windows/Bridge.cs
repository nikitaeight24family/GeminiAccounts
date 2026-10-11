using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
namespace Omni;
public sealed class Bridge : IDisposable
{
    readonly Process process;
    readonly SemaphoreSlim writeLock = new(1);
    readonly Dictionary<int, TaskCompletionSource<JsonElement>> pending = new();
    int next;
    public event Action<JsonElement>? Message;
    public Bridge(string root)
    {
        var executable = Path.Combine(AppContext.BaseDirectory, "Omni-Backend.exe");
        var packaged = File.Exists(executable);
        process = new Process { StartInfo = new ProcessStartInfo(packaged ? executable : "python") {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8,
            WorkingDirectory = root
        }};
        if (!packaged) process.StartInfo.ArgumentList.Add(Path.Combine(root,"native_bridge.py"));
    }
    public void Start()
    {
        process.Start();
        _ = Task.Run(async () => { while (await process.StandardError.ReadLineAsync() is {} _) {} });
        _ = Task.Run(async () => {
            while (await process.StandardOutput.ReadLineAsync() is {} line)
            {
                using var document = JsonDocument.Parse(line);
                var message = document.RootElement.Clone();
                if (message.TryGetProperty("id", out var id) && id.ValueKind == JsonValueKind.Number)
                {
                    TaskCompletionSource<JsonElement>? reply;
                    lock (pending) { pending.Remove(id.GetInt32(), out reply); }
                    if (message.TryGetProperty("error",out var error)) reply?.SetException(new Exception(error.GetString()));
                    else reply?.SetResult(message.GetProperty("result"));
                }
                else Message?.Invoke(message);
            }
        });
    }
    public async Task<JsonElement> Send(string action, object? fields = null)
    {
        var data = fields == null ? new Dictionary<string,object?>() :
            JsonSerializer.Deserialize<Dictionary<string,object?>>(JsonSerializer.Serialize(fields))!;
        var id = Interlocked.Increment(ref next);
        data["action"] = action; data["request"] = id;
        var source = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        lock(pending) pending[id] = source;
        await writeLock.WaitAsync();
        try { await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(data)); await process.StandardInput.FlushAsync(); }
        finally { writeLock.Release(); }
        return await source.Task.WaitAsync(TimeSpan.FromSeconds(90));
    }
    public void Dispose()
    {
        try { process.StandardInput.Close(); if (!process.HasExited) process.Kill(); } catch (InvalidOperationException) {}
        process.Dispose();
    }
}
