// FR-05: web-search toggle pill. Disabled (and explained) when the deployment
// has web search turned off in config.json.

export interface SearchToggleProps {
  enabled: boolean; // whether the deployment allows web search at all
  active: boolean; // whether the user has it switched on
  onChange: (active: boolean) => void;
}

export function SearchToggle({ enabled, active, onChange }: SearchToggleProps) {
  const disabled = !enabled;
  const title = disabled
    ? "La búsqueda web está desactivada en este equipo."
    : active
      ? "Búsqueda web activada: la consulta se enviará a la web."
      : "Búsqueda web desactivada: todo permanece local.";

  return (
    <button
      type="button"
      className={`search-pill${active ? " active" : ""}`}
      aria-pressed={active}
      disabled={disabled}
      title={title}
      onClick={() => onChange(!active)}
    >
      <span className="pill-dot" aria-hidden="true" />
      Búsqueda web {active ? "ON" : "OFF"}
    </button>
  );
}
