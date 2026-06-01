import webbrowser
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="bmw-helper", help="BMW Maintenance Helper", no_args_is_help=True)
config_app = typer.Typer(help="Vehicle configuration commands", no_args_is_help=True)
schedule_app = typer.Typer(help="Maintenance schedule commands", no_args_is_help=True)
history_app = typer.Typer(help="Service history commands", no_args_is_help=True)
estimate_app = typer.Typer(help="Shop estimate commands", no_args_is_help=True)
email_app = typer.Typer(help="Quote email commands", no_args_is_help=True)

app.add_typer(config_app, name="config")
app.add_typer(schedule_app, name="schedule")
app.add_typer(history_app, name="history")
app.add_typer(estimate_app, name="estimate")
app.add_typer(email_app, name="email")

console = Console()


@app.command()
def serve(
    port: int = typer.Option(8000, help="Port to listen on"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Skip opening browser"),
):
    """Start the web UI and open it in the browser."""
    import uvicorn
    from bmw_helper.api import api

    url = f"http://localhost:{port}"
    console.print(f"[bold green]BMW Maintenance Helper →[/bold green] {url}")
    if not no_browser:
        webbrowser.open(url)
    uvicorn.run(api, host="0.0.0.0", port=port, reload=True)


# ─── config ──────────────────────────────────────────────────────────────────

@config_app.command("show")
def config_show():
    """Display the current vehicle configuration."""
    from bmw_helper.config import load_app_config

    try:
        cfg = load_app_config()
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)

    v = cfg.vehicle
    table = Table(title=f"{v.year} {v.make} {v.model} {v.body}", box=box.ROUNDED, show_header=False)
    table.add_column("Field", style="bold cyan", width=22)
    table.add_column("Value")

    table.add_row("Owner", cfg.owner.name)
    table.add_row("Email", cfg.owner.email or "—")
    table.add_row("VIN", v.vin)
    table.add_row("Year / Make / Model", f"{v.year} {v.make} {v.model}")
    table.add_row("Body", v.body)
    table.add_row("Engine", f"{v.engine_code} — {v.engine_desc}")
    table.add_row("Transmission", f"{v.transmission_code} — {v.transmission_desc}")
    table.add_row("Drive", v.drive)
    table.add_row("Odometer", f"{v.odometer_km:,} km")

    console.print(table)
    console.print(
        f"\n[dim]Currency:[/dim] {cfg.preferences.currency}  "
        f"[dim]{cfg.preferences.tax_name}:[/dim] {cfg.preferences.tax_rate * 100:.0f}%"
    )
    if cfg.preferences.preferred_brands:
        console.print(f"[dim]Preferred brands:[/dim] {', '.join(cfg.preferences.preferred_brands)}")


# ─── schedule ────────────────────────────────────────────────────────────────

@schedule_app.command("status")
def schedule_status():
    """Print maintenance status for all scheduled items."""
    from bmw_helper.config import load_app_config, load_schedule, load_service_history
    from bmw_helper.models import MaintenanceStatus
    from bmw_helper.schedule import compute_status

    cfg = load_app_config()
    schedule = load_schedule()
    history = load_service_history(cfg.vehicle.vin)
    statuses = compute_status(
        schedule, history,
        cfg.vehicle.odometer_km,
        manufacture_date=cfg.vehicle.manufacture_date,
    )

    if not statuses:
        console.print(
            "[yellow]No schedule items found.[/yellow] "
            "Run: [bold]bmw-helper schedule import <file.pdf>[/bold]"
        )
        return

    status_labels = {
        MaintenanceStatus.OVERDUE:  "[bold red]OVERDUE[/bold red]",
        MaintenanceStatus.DUE_SOON: "[bold yellow]DUE SOON[/bold yellow]",
        MaintenanceStatus.OK:       "[green]OK[/green]",
        MaintenanceStatus.UNKNOWN:  "[dim]UNKNOWN[/dim]",
    }

    from datetime import date as date_type

    today = date_type.today()

    table = Table(
        title=f"Maintenance Status — {cfg.vehicle.odometer_km:,} km  ·  {today.isoformat()}",
        box=box.ROUNDED,
    )
    table.add_column("Item", style="bold", min_width=28)
    table.add_column("Last Done", style="dim")
    table.add_column("Last km", justify="right", style="dim")
    table.add_column("Due km", justify="right")
    table.add_column("Due date", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("km left / over", justify="right")
    table.add_column("days left / over", justify="right")

    for s in statuses:
        last_date = s.last_event.date.isoformat() if s.last_event else "—"
        last_km   = f"{s.last_event.odometer_km:,}" if s.last_event else "—"
        due_km    = f"{s.next_due_km:,}" if s.next_due_km else "—"
        due_date  = s.next_due_date.isoformat() if s.next_due_date else "—"

        if s.overdue_by_km is not None and s.overdue_by_km > 0:
            km_col = f"[red]+{s.overdue_by_km:,}[/red]"
        elif s.remaining_km is not None:
            c = "yellow" if s.status == MaintenanceStatus.DUE_SOON else "dim"
            km_col = f"[{c}]{s.remaining_km:,}[/{c}]"
        else:
            km_col = "—"

        if s.overdue_by_days is not None and s.overdue_by_days > 0:
            day_col = f"[red]+{s.overdue_by_days}d[/red]"
        elif s.remaining_days is not None:
            c = "yellow" if s.status == MaintenanceStatus.DUE_SOON else "dim"
            day_col = f"[{c}]{s.remaining_days}d[/{c}]"
        else:
            day_col = "—"

        table.add_row(
            s.item.name, last_date, last_km, due_km, due_date,
            status_labels[s.status], km_col, day_col,
        )

    console.print(table)


@schedule_app.command("import")
def schedule_import(
    pdf_path: Path = typer.Argument(..., help="Path to maintenance schedule PDF"),
):
    """Parse a maintenance schedule PDF into config/schedule.yaml. (Phase 2)"""
    console.print(f"[yellow]Schedule PDF import coming in Phase 2 — {pdf_path}[/yellow]")


# ─── history ─────────────────────────────────────────────────────────────────

@history_app.command("record")
def history_record(
    item_id: str = typer.Argument(..., help="Schedule item ID (e.g. oil_filter)"),
    km: int = typer.Option(..., "--km", help="Odometer reading when service was performed"),
    date_str: str = typer.Option(None, "--date", help="Date as YYYY-MM-DD (defaults to today)"),
    by: str = typer.Option(None, "--by", help='Who performed the work: "Self" or shop name'),
    part: list[str] = typer.Option(None, "--part", help='Part used — repeat for multiple: --part "11127565286 Elring" --part "07119963182"'),
    notes: str = typer.Option(None, "--notes", help="Free-form notes (fluid spec, warranty info, etc.)"),
):
    """Record a completed service event.

    Examples:

      # Done at a shop
      bmw-helper history record brake_fluid --km 84000 --date 2026-06-01 --by "Eurotekk" --part "DOT 4 LV Ate" --notes "Bled all four corners"

      # DIY
      bmw-helper history record oil_filter --km 84000 --by Self --part "11428637821 Elring" --part "07119963182" --notes "Liqui Moly 5W-30 6L"
    """
    from datetime import date as date_type

    from bmw_helper.config import load_app_config, load_service_history, save_service_history
    from bmw_helper.models import ServiceEvent

    cfg = load_app_config()
    history = load_service_history(cfg.vehicle.vin)

    event_date = date_type.fromisoformat(date_str) if date_str else date_type.today()
    event = ServiceEvent(
        item_id=item_id,
        date=event_date,
        odometer_km=km,
        performed_by=by,
        parts=part or [],
        notes=notes,
    )
    history.history.append(event)
    save_service_history(history)

    console.print(f"[green]Recorded:[/green] [bold]{item_id}[/bold] at {km:,} km on {event_date}")
    if by:
        console.print(f"  [dim]Performed by:[/dim] {by}")
    for p in (part or []):
        console.print(f"  [dim]Part:[/dim] {p}")
    if notes:
        console.print(f"  [dim]Notes:[/dim] {notes}")


@history_app.command("show")
def history_show(
    item_id: str = typer.Argument(None, help="Filter to a specific item ID"),
):
    """Show service history for all items or a specific one."""
    from bmw_helper.config import load_app_config, load_service_history

    cfg = load_app_config()
    history = load_service_history(cfg.vehicle.vin)
    events = history.history
    if item_id:
        events = [e for e in events if e.item_id == item_id]

    if not events:
        console.print("[dim]No service history recorded.[/dim]")
        return

    table = Table(title="Service History", box=box.ROUNDED)
    table.add_column("ID", style="dim", width=10)
    table.add_column("Item", style="bold")
    table.add_column("Date")
    table.add_column("Odometer", justify="right")
    table.add_column("Performed by")
    table.add_column("Parts")
    table.add_column("Notes")

    for e in sorted(events, key=lambda x: x.odometer_km, reverse=True):
        parts_str = "\n".join(e.parts) if e.parts else "—"
        table.add_row(
            e.id,
            e.item_id,
            e.date.isoformat(),
            f"{e.odometer_km:,} km",
            e.performed_by or "—",
            parts_str,
            e.notes or "—",
        )

    console.print(table)


# ─── estimate ────────────────────────────────────────────────────────────────

@estimate_app.command("import")
def estimate_import(
    pdf_path: Path = typer.Argument(..., help="Path to shop estimate PDF"),
):
    """Parse a shop estimate PDF into estimates/. (Phase 7)"""
    console.print(f"[yellow]Estimate import coming in Phase 7 — {pdf_path}[/yellow]")


# ─── email ───────────────────────────────────────────────────────────────────

@email_app.command("generate")
def email_generate(
    plan_id: str = typer.Argument(..., help="Service plan ID"),
    output: Path = typer.Option(None, "--output", "-o", help="Write to file instead of stdout"),
):
    """Render a quote-request email for a service plan. (Phase 6)"""
    console.print(f"[yellow]Email generator coming in Phase 6 — plan: {plan_id}[/yellow]")
