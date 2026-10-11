import SwiftUI
import AppKit

struct Quota: Decodable, Identifiable {
    var id: String; var label: String; var family: String
    var remaining: Double?; var floor: Double; var reset: Double?
}
struct Account: Decodable, Identifiable {
    var id: String; var provider: String; var label: String; var plan: String
    var status: String; var priority: Int; var disabled: Bool; var windows: [Quota]
    var resetCredits: Int?; var resetAvailable: Bool?
}
struct Preferences: Decodable {
    var theme: String; var language: String; var `private`: Bool; var visible: [String: Bool]
}
@MainActor final class Model: ObservableObject {
    @Published var accounts: [Account] = []
    @Published var visible: [String: Bool] = [:]
    @Published var theme = "dark"
    @Published var language = "en"
    @Published var privateNames = false
    @Published var notice = ""
    private var process: Process?
    private let input = Pipe()
    private var buffer = Data()
    private var request = 0
    private var poll: Timer?
    let providers = ["gemini", "openai", "claude", "grok", "tokenharbor"]
    func start() {
        guard process == nil else { return }
        let runner = Process(); let output = Pipe()
        let root = ProcessInfo.processInfo.environment["OMNI_SOURCE_ROOT"] ?? FileManager.default.currentDirectoryPath
        let packaged = Bundle.main.bundleURL.deletingLastPathComponent().appendingPathComponent("Omni-Backend")
        if FileManager.default.isExecutableFile(atPath: packaged.path) { runner.executableURL = packaged }
        else { runner.executableURL = URL(fileURLWithPath: "/usr/bin/env"); runner.arguments = ["python3", root + "/native_bridge.py"] }
        runner.standardInput = input; runner.standardOutput = output; runner.standardError = FileHandle.nullDevice
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let chunk = handle.availableData
            Task { @MainActor in self?.read(chunk) }
        }
        do { try runner.run(); process = runner }
        catch { notice = error.localizedDescription }
        poll = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in Task { @MainActor in self?.send("refresh") } }
    }
    func send(_ action: String, _ fields: [String: Any] = [:]) {
        var payload = fields; request += 1; payload["request"] = request; payload["action"] = action
        do { var data = try JSONSerialization.data(withJSONObject: payload); data.append(10); try input.fileHandleForWriting.write(contentsOf: data) }
        catch { notice = error.localizedDescription }
    }
    func read(_ chunk: Data) {
        buffer.append(chunk)
        while let newline = buffer.firstIndex(of: 10) {
            let line = buffer.prefix(upTo: newline); buffer.removeSubrange(...newline)
            guard let json = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else { continue }
            switch json["event"] as? String {
            case "account":
                if let raw = json["account"], let data = try? JSONSerialization.data(withJSONObject: raw), let account = try? JSONDecoder().decode(Account.self, from: data) {
                    if let index = accounts.firstIndex(where: { $0.id == account.id }) { accounts[index] = account } else { accounts.append(account) }
                }
            case "accounts":
                if let ids = json["ids"] as? [String] { accounts.removeAll { !ids.contains($0.id) } }
            case "preferences":
                if let raw = json["preferences"], let data = try? JSONSerialization.data(withJSONObject: raw), let prefs = try? JSONDecoder().decode(Preferences.self, from: data) {
                    visible = prefs.visible; theme = prefs.theme; language = prefs.language; privateNames = prefs.private
                }
            case "error", "notice": notice = json["message"] as? String ?? ""
            default:
                if let result = json["result"] as? [String: Any], let url = result["url"] as? String, let target = URL(string: url) {
                    NSWorkspace.shared.open(target); notice = result["user_code"] as? String ?? "Complete sign-in in your browser"
                }
                if let error = json["error"] as? String { notice = error }
            }
        }
    }
    func stop() { poll?.invalidate(); process?.terminate() }
    func text(_ en: String, _ ru: String) -> String { language == "ru" ? ru : en }
}

struct AccountCard: View {
    @ObservedObject var model: Model
    let account: Account
    @State private var renaming = false
    @State private var newName = ""
    @State private var resetting = false
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(model.privateNames ? account.provider : account.label).lineLimit(1)
                    .onTapGesture { newName = ""; renaming = true }
                Spacer()
                Button(account.disabled ? "▶" : "⏸") { model.send("pause", ["id": account.id]) }
                    .help(model.text(account.disabled ? "Resume account" : "Pause account", account.disabled ? "Возобновить аккаунт" : "Приостановить аккаунт"))
            }
            HStack {
                Text(account.plan).font(.caption.bold()).padding(3).background(.blue.opacity(0.2)).cornerRadius(4)
                Text(account.status).font(.caption)
                Spacer()
                Button("↓") { model.send("priority", ["id": account.id, "delta": -1]) }
                Text(String(account.priority))
                Button("↑") { model.send("priority", ["id": account.id, "delta": 1]) }
            }
            ForEach(account.windows) { quota in QuotaRow(model: model, account: account.id, quota: quota) }
            if (account.resetCredits ?? 0) > 0 || account.resetAvailable == true {
                Button(model.text("Reset usage", "Сбросить лимиты")) { resetting = true }
                    .disabled(account.resetAvailable != true || account.disabled)
                    .help(model.text("OpenAI must allow the reset for this account", "OpenAI должен разрешить сброс для этого аккаунта"))
            }
        }.padding(8).background(.quaternary).cornerRadius(8)
        .alert(model.text("New account name", "Новое название аккаунта"), isPresented: $renaming) {
            TextField("", text: $newName)
            Button(model.text("Save", "Сохранить")) { model.send("rename", ["id": account.id, "label": newName]) }
            Button(model.text("Cancel", "Отмена"), role: .cancel) {}
        }
        .confirmationDialog(model.text("Use one reset credit?", "Использовать один сброс?"), isPresented: $resetting) {
            Button(model.text("Reset usage", "Сбросить лимиты")) { model.send("reset", ["id": account.id]) }
        }
    }
}
struct QuotaRow: View {
    @ObservedObject var model: Model
    let account: String
    let quota: Quota
    @State var floor: Double = 0
    var body: some View {
        HStack {
            Text(quota.label + " · " + (quota.remaining.map { String(Int($0)) + "%" } ?? "—")).font(.caption).frame(width: 70, alignment: .leading)
            ZStack {
                ProgressView(value: quota.remaining ?? 0, total: 100)
                Slider(value: $floor, in: 0...100, step: 1) { editing in
                    if !editing { model.send("floor", ["id": account, "window": quota.id, "value": Int(floor)]) }
                }.help(String(Int(floor)) + "%")
            }
        }.onAppear { floor = quota.floor }.onChange(of: quota.floor) { floor = $0 }
    }
}
struct Content: View {
    @StateObject var model = Model()
    @State var settings = false
    @State var collapsed: Set<String> = []
    @State var apiProvider: String?
    @State var key = ""
    @State var label = ""
    var body: some View {
        HStack(spacing: 20) {
            VStack {
                HStack {
                    Text("Omni").font(.title.bold()); Spacer()
                    Button(model.privateNames ? "◉" : "◎") { model.send("private", ["value": !model.privateNames]) }
                    Button("⚙") { settings.toggle() }
                }
                ScrollView {
                    VStack {
                        ForEach(model.providers.filter { model.visible[$0] ?? true }, id: \.self) { provider in
                            HStack {
                                Button((collapsed.contains(provider) ? "▸ " : "▾ ") + provider.capitalized + " · " + String(model.accounts.filter { $0.provider == provider }.count) + "pcs") {
                                    if collapsed.contains(provider) { collapsed.remove(provider) } else { collapsed.insert(provider) }
                                }
                                Spacer()
                                Menu("+") {
                                    Button(model.text("Sign in", "Войти")) { model.send("login", ["provider": provider]) }
                                    Button("API") { apiProvider = provider }
                                }
                            }
                            if !collapsed.contains(provider) {
                                ForEach(model.accounts.filter { $0.provider == provider }.sorted { $0.priority > $1.priority }) { account in AccountCard(model: model, account: account) }
                            }
                        }
                    }
                }
                ForEach(model.providers.filter { model.visible[$0] ?? true }, id: \.self) { provider in
                    Text(provider.capitalized).font(.caption).frame(maxWidth: .infinity, alignment: .leading)
                }
            }.frame(width: 300)
            VStack(alignment: .leading) {
                if settings {
                    Text(model.text("Display settings", "Настройки отображения")).font(.title)
                    ForEach(model.providers, id: \.self) { provider in
                        Toggle(provider.capitalized, isOn: Binding(get: { model.visible[provider] ?? true }, set: {
                            model.visible[provider] = $0; model.send("visibility", ["provider": provider, "value": $0])
                        }))
                    }
                    Picker(model.text("Theme", "Тема"), selection: Binding(get: { model.theme }, set: { model.theme = $0; model.send("theme", ["value": $0]) })) {
                        Text("Dark").tag("dark"); Text("Light").tag("light")
                    }
                    Picker(model.text("Language", "Язык"), selection: Binding(get: { model.language }, set: { model.language = $0; model.send("language", ["value": $0]) })) {
                        Text("English").tag("en"); Text("Русский").tag("ru")
                    }
                } else {
                    Text(model.text("Saved accounts", "Сохранённые аккаунты")).font(.title)
                    Button(model.text("Automatic routing", "Автоматический выбор")) { model.send("route") }
                }
                Text(model.notice).font(.caption); Spacer()
            }.frame(maxWidth: .infinity, alignment: .leading)
        }.padding(16).frame(minWidth: 760, minHeight: 540)
        .preferredColorScheme(model.theme == "light" ? .light : .dark)
        .onAppear { model.start() }.onDisappear { model.stop() }
        .sheet(isPresented: Binding(get: { apiProvider != nil }, set: { if !$0 { apiProvider = nil } })) {
            VStack {
                Text("API · " + (apiProvider ?? "")); TextField("Account name", text: $label); SecureField("API key", text: $key)
                Button("Connect") { model.send("api", ["provider": apiProvider == "openai" ? "OpenAI" : apiProvider == "tokenharbor" ? "TokenHarbor" : (apiProvider ?? "").capitalized, "key": key, "label": label]); key = ""; apiProvider = nil }
            }.padding(20).frame(width: 380)
        }
    }
}
@main struct OmniApp: App {
    var body: some Scene { WindowGroup("Omni") { Content() } }
}
