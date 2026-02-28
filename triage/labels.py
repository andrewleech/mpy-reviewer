"""Label taxonomy mapping for MicroPython issue triage.

Maps from internal categorization fields (component, port, issue type)
to the actual GitHub label names used in micropython/micropython.
"""

# All valid labels on micropython/micropython that triage may apply.
VALID_LABELS: set[str] = {
    # Component labels
    "py-core",
    "extmod",
    "drivers",
    "tools",
    "tests",
    "docs",
    "examples",
    # Port labels
    "port-bare-arm",
    "port-cc3200",
    "port-esp32",
    "port-esp8266",
    "port-mimxrt",
    "port-minimal",
    "port-nrf",
    "port-pic16bit",
    "port-powerpc",
    "port-qemu",
    "port-renesas-ra",
    "port-rp2",
    "port-samd",
    "port-stm32",
    "port-unix",
    "port-webassembly",
    "port-windows",
    "port-zephyr",
    # Type labels
    "bug",
    "enhancement",
    "rfc",
    # Status labels (auto-applied by triage)
    "needs-info",
    "proposed-close",
    # Subsystem labels
    "bluetooth",
    "networking",
}

# Map from internal component field to GitHub label.
COMPONENT_TO_LABEL: dict[str, str] = {
    "py_core": "py-core",
    "extmod": "extmod",
    "drivers": "drivers",
    "tools": "tools",
    "tests": "tests",
    "docs": "docs",
    "examples": "examples",
    "build_system": "tools",
    "port_specific": "",  # needs port label instead
}

# Map from internal port field to GitHub label.
PORT_TO_LABEL: dict[str, str] = {
    "bare-arm": "port-bare-arm",
    "cc3200": "port-cc3200",
    "esp32": "port-esp32",
    "esp8266": "port-esp8266",
    "mimxrt": "port-mimxrt",
    "minimal": "port-minimal",
    "nrf": "port-nrf",
    "pic16bit": "port-pic16bit",
    "powerpc": "port-powerpc",
    "qemu": "port-qemu",
    "renesas-ra": "port-renesas-ra",
    "rp2": "port-rp2",
    "samd": "port-samd",
    "stm32": "port-stm32",
    "unix": "port-unix",
    "webassembly": "port-webassembly",
    "windows": "port-windows",
    "zephyr": "port-zephyr",
}

# Map from issue type description to GitHub label.
ISSUE_TYPE_TO_LABEL: dict[str, str] = {
    "bug": "bug",
    "enhancement": "enhancement",
    "feature_request": "enhancement",
    "rfc": "rfc",
    "discussion": "rfc",
}

# Map from subsystem to GitHub label (only for subsystems that have labels).
SUBSYSTEM_TO_LABEL: dict[str, str] = {
    "bluetooth": "bluetooth",
    "networking": "networking",
    "wifi": "networking",
    "ethernet": "networking",
    "socket": "networking",
}


def resolve_labels(
    component: str | None = None,
    port: str | None = None,
    issue_type: str | None = None,
    subsystem: str | None = None,
) -> set[str]:
    """Resolve internal fields to a set of valid GitHub labels."""
    labels = set()

    if component and component in COMPONENT_TO_LABEL:
        label = COMPONENT_TO_LABEL[component]
        if label:
            labels.add(label)

    if port and port in PORT_TO_LABEL:
        labels.add(PORT_TO_LABEL[port])

    if issue_type and issue_type in ISSUE_TYPE_TO_LABEL:
        labels.add(ISSUE_TYPE_TO_LABEL[issue_type])

    if subsystem and subsystem in SUBSYSTEM_TO_LABEL:
        labels.add(SUBSYSTEM_TO_LABEL[subsystem])

    # Final validation
    return labels & VALID_LABELS
