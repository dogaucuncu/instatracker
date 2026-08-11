#!/usr/bin/env python3
"""
InstaTracker CLI — Terminal arayüzü
Kullanım: python cli.py <komut>
"""
import sys
import json
from pathlib import Path

# Add backend dir to path
sys.path.insert(0, str(Path(__file__).parent))

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.text import Text
from rich.prompt import Prompt, Confirm

import database as db
from services import instagram_service as ig
from services import tracker_service

console = Console()


def _check_login():
    """Ensure user is logged in, prompt if not."""
    if ig.is_logged_in():
        return True
    # Try loading session
    if ig.load_session():
        return True
    console.print("[yellow]⚠ Giriş yapılmamış. Lütfen önce 'python cli.py login' komutunu çalıştırın.[/]")
    return False


@click.group()
def cli():
    """🔍 InstaTracker — Instagram Takipçi Takip Sistemi"""
    db.init_db()


@cli.command()
def login():
    """Instagram hesabınıza giriş yapın."""
    console.print(Panel("[bold magenta]InstaTracker — Giriş[/]", box=box.ROUNDED))
    username = Prompt.ask("📧 Instagram kullanıcı adı")
    password = Prompt.ask("🔑 Şifre", password=True)

    with console.status("[bold green]Giriş yapılıyor..."):
        result = ig.login(username, password)

    if result["status"] == "ok":
        info = ig.get_account_info()
        db.save_account(info["pk"], info["username"], info["full_name"], info["profile_pic_url"])
        console.print(f"[bold green]✓ Giriş başarılı! Hoş geldiniz, @{info['username']}[/]")
    elif result["status"] == "2fa_required":
        console.print("[yellow]📱 2FA doğrulaması gerekiyor.[/]")
        code = Prompt.ask("Doğrulama kodunu girin")
        result2 = ig.verify_2fa(code)
        if result2["status"] == "ok":
            info = ig.get_account_info()
            db.save_account(info["pk"], info["username"], info["full_name"], info["profile_pic_url"])
            console.print(f"[bold green]✓ Giriş başarılı! Hoş geldiniz, @{info['username']}[/]")
        else:
            console.print(f"[red]✗ 2FA hatası: {result2.get('message')}[/]")
    else:
        console.print(f"[red]✗ Giriş başarısız: {result.get('message')}[/]")


@cli.command()
def logout():
    """Çıkış yapın."""
    ig.logout()
    db.clear_account()
    console.print("[green]✓ Çıkış yapıldı.[/]")


@cli.command()
def status():
    """Giriş durumunu ve hesap bilgilerini göster."""
    account = db.get_account()
    if account and ig.is_logged_in():
        stats = db.get_dashboard_stats()
        console.print(Panel(
            f"[bold]👤 @{account['username']}[/]\n"
            f"[dim]{account.get('full_name', '')}[/]\n\n"
            f"👥 Takipçi: [cyan]{stats['follower_count']}[/]  |  "
            f"👣 Takip: [cyan]{stats['following_count']}[/]\n"
            f"📊 Toplam tarama: [cyan]{stats['total_scans']}[/]\n"
            f"🕐 Son tarama: [cyan]{stats.get('last_scan', 'Henüz yok')}[/]",
            title="[magenta]Hesap Durumu[/]",
            box=box.ROUNDED,
        ))
    else:
        console.print("[yellow]⚠ Giriş yapılmamış.[/]")


@cli.command()
def scan():
    """Takipçi listesini tara ve değişiklikleri tespit et."""
    if not _check_login():
        return

    try:
        tracker_service.check_scan_allowed()
    except tracker_service.ScanTooSoon as e:
        console.print(f"[yellow]⏳ {e}[/]")
        return

    console.print(Panel("[bold cyan]🔍 Tarama Başlatılıyor...[/]", box=box.ROUNDED))
    console.print("[dim]Bu işlem hesabınızdaki takipçi sayısına bağlı olarak birkaç dakika sürebilir.[/]\n")

    with console.status("[bold green]Takipçiler ve takip edilenler çekiliyor..."):
        try:
            result = tracker_service.run_scan()
        except Exception as e:
            console.print(f"[red]✗ Tarama hatası: {e}[/]")
            return

    status_icon = "✓" if result["status"] in ("completed", "first_scan") else "✗"
    color = "green" if result["status"] in ("completed", "first_scan") else "red"

    console.print(f"[bold {color}]{status_icon} {result['message']}[/]\n")

    if result["status"] == "completed":
        table = Table(box=box.SIMPLE_HEAVY)
        table.add_column("Metrik", style="bold")
        table.add_column("Değer", style="cyan")
        table.add_row("🆕 Yeni Takipçi", str(result["new_followers"]))
        table.add_row("👋 Takipten Çıkan", str(result["lost_followers"]))
        table.add_row("📝 Yeni Kayıt", str(result["events_created"]))
        console.print(table)


@cli.command()
def unfollowers():
    """Sizi takipten çıkan kullanıcıları listele."""
    if not _check_login():
        return
    events = db.get_events(event_type="unfollowed", limit=100)
    _print_event_table(events, "👋 Takipten Çıkanlar", "unfollowed")


@cli.command()
def blockers():
    """Sizi engelleyen kullanıcıları listele."""
    if not _check_login():
        return
    events = db.get_events(event_type="blocked", limit=100)
    _print_event_table(events, "🚫 Engelleyenler", "blocked")


@cli.command()
def deactivated():
    """Hesabını kapatan/devre dışı bırakan kullanıcıları listele."""
    if not _check_login():
        return
    events = db.get_events(event_type="deactivated", limit=100)
    _print_event_table(events, "⛔ Hesap Kapatanlar", "deactivated")


@cli.command()
def new_followers():
    """Yeni takipçileri listele."""
    if not _check_login():
        return
    events = db.get_events(event_type="new_follower", limit=100)
    _print_event_table(events, "🆕 Yeni Takipçiler", "new_follower")


def _print_event_table(events: list, title: str, event_type: str):
    if not events:
        console.print(f"[yellow]Henüz kayıtlı {title.lower()} yok.[/]")
        return

    table = Table(title=title, box=box.ROUNDED, show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Kullanıcı Adı", style="bold magenta")
    table.add_column("Ad Soyad", style="white")
    table.add_column("Tarih", style="dim")

    if event_type in ("unfollowed", "blocked", "deactivated"):
        table.add_column("Hala Takip?", style="bold")

    for i, ev in enumerate(events, 1):
        row = [
            str(i),
            f"@{ev['username']}",
            ev.get("full_name") or "",
            ev["detected_at"][:16].replace("T", " "),
        ]
        if event_type in ("unfollowed", "blocked", "deactivated"):
            if ev["still_following"]:
                row.append("[bold yellow]⚠ Evet[/]")
            else:
                row.append("[green]Hayır[/]")
        table.add_row(*row)

    console.print(table)
    console.print(f"[dim]Toplam: {len(events)} kayıt[/]")


@cli.command()
@click.argument("username")
def unfollow(username: str):
    """Belirli bir kullanıcıyı takipten çık.\n\nÖrnek: python cli.py unfollow kullanici_adi"""
    if not _check_login():
        return

    if not Confirm.ask(f"[yellow]@{username}[/] kullanıcısını takipten çıkmak istediğinizden emin misiniz?"):
        console.print("[dim]İptal edildi.[/]")
        return

    # Find user_pk from events
    events = db.get_events(limit=500)
    user_pk = None
    for ev in events:
        if ev["username"].lower() == username.lower():
            user_pk = ev["user_pk"]
            break

    if not user_pk:
        console.print(f"[red]@{username} kullanıcısı kayıtlarda bulunamadı.[/]")
        return

    with console.status(f"[yellow]@{username} takipten çıkılıyor..."):
        success = ig.unfollow_user(user_pk)

    if success:
        db.update_event_still_following(user_pk, False)
        console.print(f"[bold green]✓ @{username} takipten çıkarıldı.[/]")
    else:
        console.print(f"[red]✗ @{username} takipten çıkarılırken hata oluştu.[/]")


@cli.command()
def stats():
    """Genel istatistikleri göster."""
    data = db.get_dashboard_stats()

    table = Table(title="📊 InstaTracker İstatistikleri", box=box.ROUNDED)
    table.add_column("Metrik", style="bold white")
    table.add_column("Değer", style="bold cyan", justify="right")

    table.add_row("👥 Mevcut Takipçi", str(data["follower_count"]))
    table.add_row("👣 Takip Ettiklerim", str(data["following_count"]))
    table.add_row("─" * 20, "─" * 10)
    table.add_row("👋 Takipten Çıkanlar", str(data["unfollowed"]))
    table.add_row("🚫 Engelleyenler", str(data["blocked"]))
    table.add_row("⛔ Hesap Kapatanlar", str(data["deactivated"]))
    table.add_row("🆕 Yeni Takipçiler", str(data["new_followers"]))
    table.add_row("─" * 20, "─" * 10)
    table.add_row("⚠  Hala Takip Ettiklerim", str(data["still_following_count"]))
    table.add_row("─" * 20, "─" * 10)
    table.add_row("🔍 Toplam Tarama", str(data["total_scans"]))
    table.add_row("🕐 Son Tarama", data.get("last_scan", "Henüz yok") or "Henüz yok")

    console.print(table)


if __name__ == "__main__":
    cli()
