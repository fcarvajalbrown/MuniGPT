import { useEffect, useState } from "react";
import { fetchConfig, type AppConfig } from "./api";
import { Chat } from "./components/Chat";

export function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [configError, setConfigError] = useState(false);

  useEffect(() => {
    fetchConfig()
      .then(setConfig)
      // Fall back to safe defaults if the backend isn't up yet; the Electron
      // splash normally waits for /status, so this is a defensive default.
      .catch(() => setConfigError(true));
  }, []);

  const municipio = config?.municipio ?? "MuniGPT";
  const webSearchEnabled = config?.webSearchEnabled ?? false;

  return (
    <div className="app">
      <header className="topbar">
        {config?.logo && (
          <img
            className="brand-logo"
            src={config.logo}
            alt=""
            onError={(e) => (e.currentTarget.style.display = "none")}
          />
        )}
        <div className="brand-text">
          <div className="brand-name">{municipio}</div>
          <div className="brand-sub">Asistente legal municipal · funciona sin conexión</div>
        </div>
      </header>

      {configError && (
        <div className="banner">
          No se pudo leer la configuración del municipio; usando valores por defecto.
        </div>
      )}

      <main className="main">
        <Chat webSearchEnabled={webSearchEnabled} />
      </main>
    </div>
  );
}
