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
  // FR-08: soft enforcement — show a banner when the license is absent, expired,
  // or invalid, but never block the chat.
  const license = config?.licenseStatus;
  const showLicenseBanner = license != null && !license.valid;

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

      {showLicenseBanner && (
        <div className="banner banner-license">
          {license?.state === "missing"
            ? "Esta copia no está activada. Solicite una licencia a Instituto Igualdad."
            : license?.reason ?? "La licencia de esta copia no es válida."}
        </div>
      )}

      <main className="main">
        <Chat webSearchEnabled={webSearchEnabled} />
      </main>
    </div>
  );
}
