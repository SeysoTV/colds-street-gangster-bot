from datetime import datetime, time
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands, tasks

# ==========================================
# EINSTELLUNGEN FÜR AUTOMATISCHE AUFSTELLUNG
# ==========================================
AUFSTELLUNG_KANAL_ID = 123456789012345678  # ERSETZE DIES DURCH DEINE KANAL-ID!
ROLLE_NAME = "CSG"
UHRZEIT_POST = time(hour=15, minute=0)


# --- DATENBANK EINRICHTUNG ---
def init_db():
  conn = sqlite3.connect("lager.db")
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            name TEXT PRIMARY KEY,
            quantity INTEGER,
            min_quantity INTEGER
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            action TEXT,
            details TEXT,
            user TEXT
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS abmeldungen (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            zeitraum TEXT,
            grund TEXT
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS wochenabgabe (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            status TEXT
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS einstellungen (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS termine (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titel TEXT,
            datum_uhrzeit TEXT,
            beschreibung TEXT,
            erstellt_von TEXT
        )
    """)
  cursor.execute(
      "INSERT OR IGNORE INTO einstellungen (key, value) VALUES"
      " ('wochenabgabe_betrag', '50000')"
  )
  conn.commit()
  conn.close()


init_db()


def log_action(action: str, details: str, user: str):
  timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
  conn = sqlite3.connect("lager.db")
  cursor = conn.cursor()
  cursor.execute(
      "INSERT INTO logs (timestamp, action, details, user) VALUES (?, ?, ?, ?)",
      (timestamp, action, details, user),
  )
  conn.commit()
  conn.close()

  global live_log_message
  if live_log_message:
    try:
      bot.loop.create_task(live_log_message.edit(embed=get_log_embed()))  # type: ignore[attr-defined]
    except Exception:
      pass


def get_einstellung(key):
  conn = sqlite3.connect("lager.db")
  cursor = conn.cursor()
  cursor.execute("SELECT value FROM einstellungen WHERE key = ?", (key,))
  row = cursor.fetchone()
  conn.close()
  return row[0] if row else None


# --- EMBED HELFER ---
def get_bestand_embed():
  conn = sqlite3.connect("lager.db")
  cursor = conn.cursor()
  cursor.execute("SELECT name, quantity, min_quantity FROM items")
  rows = cursor.fetchall()
  conn.close()

  embed = discord.Embed(
      title="📦 Live-Lagerbestand",
      description=(
          "Dieser Bestand aktualisiert sich automatisch bei jeder"
          " Buchung.\n\n"
      ),
      color=discord.Color.from_rgb(230, 126, 34),
  )

  if not rows:
    embed.description += "Das Lager ist aktuell leer."
  else:
    desc = ""
    for name, qty, min_qty in rows:
      warning = " ⚠️ (unter Mindestbestand!)" if qty < min_qty else ""
      desc += f"**{name}**: **{qty}**{warning}\n"
    embed.description += desc

  embed.set_footer(
      text=f"Zuletzt aktualisiert: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
  )
  return embed


def get_abmeldungen_embed():
  conn = sqlite3.connect("lager.db")
  cursor = conn.cursor()
  cursor.execute("SELECT username, zeitraum, grund FROM abmeldungen")
  rows = cursor.fetchall()
  conn.close()

  embed = discord.Embed(
      title="Aktive & geplante Abmeldungen",
      color=discord.Color.from_rgb(52, 152, 219),
  )

  if not rows:
    embed.description = "Aktuell ist niemand abgemeldet."
  else:
    desc = ""
    for username, zeitraum, grund in rows:
      desc += f"• **{username}** | Zeitraum: *{zeitraum}* | Grund: *{grund}*\n"
    embed.description = desc

  embed.set_footer(text="Sortiert nach Startdatum • Zeitzone: Europe/Berlin")
  return embed


def get_wochenabgabe_embed():
  betrag_str = get_einstellung("wochenabgabe_betrag") or "50000"
  try:
    betrag_int = int(betrag_str)
  except ValueError:
    betrag_int = 50000

  conn = sqlite3.connect("lager.db")
  cursor = conn.cursor()
  cursor.execute("SELECT username, status FROM wochenabgabe")
  rows = cursor.fetchall()
  conn.close()

  abgegeben = [r[0] for r in rows if r[1] == "abgegeben"]
  offen = [r[0] for r in rows if r[1] == "offen"]
  befreit = [r[0] for r in rows if r[1] == "befreit"]
  eingenommen = len(abgegeben) * betrag_int

  embed = discord.Embed(
      title="Wochenabgabe KW 42",
      description=(
          f"**Zeitraum:** 12.10.2026 bis 18.10.2026\n**Betrag:**"
          f" {betrag_int:,}$ pro Mitglied\n**Frist:** Sonntag, 18.10.2026 20:00"
          f" Uhr\n**Bei Versäumnis:** automatische Sanktion über"
          f" {betrag_int:,}$\n**Eingenommen:** {eingenommen:,}$"
      ),
      color=discord.Color.from_rgb(241, 196, 15),
  )

  abgegeben_str = (
      "\n".join([f"• **{u}**" for u in abgegeben]) if abgegeben else "Keine"
  )
  offen_str = "\n".join([f"• **{u}**" for u in offen]) if offen else "Keine"
  befreit_str = "\n".join([f"• **{u}**" for u in befreit]) if befreit else "Keine"

  embed.add_field(
      name=f"✅ Abgegeben ({len(abgegeben)})", value=abgegeben_str, inline=False
  )
  embed.add_field(
      name=f"❌ Offen ({len(offen)})", value=offen_str, inline=False
  )
  embed.add_field(
      name=f"🟦 Befreit ({len(befreit)})", value=befreit_str, inline=False
  )

  embed.set_footer(text="Aktualisiert • Zeitzone: Europe/Berlin")
  return embed


def get_log_embed():
  conn = sqlite3.connect("lager.db")
  cursor = conn.cursor()
  cursor.execute(
      "SELECT timestamp, action, details, user FROM logs ORDER BY id DESC LIMIT"
      " 15"
  )
  rows = cursor.fetchall()
  conn.close()

  embed = discord.Embed(
      title="📜 Live-Aktivitäts-Log",
      description=(
          "Hier werden alle Aktionen des Bots in Echtzeit"
          " protokolliert.\n\n"
      ),
      color=discord.Color.from_rgb(155, 89, 182),
  )

  if not rows:
    embed.description += "Bisher keine Aktivitäten aufgezeichnet."
  else:
    desc = ""
    for r in rows:
      desc += f"[`{r[0]}`] **{r[1]}** | {r[2]} — *{r[3]}*\n"
    embed.description += desc

  embed.set_footer(
      text=f"Letzte Aktualisierung: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
  )
  return embed


def get_kalender_embed():
  conn = sqlite3.connect("lager.db")
  cursor = conn.cursor()
  cursor.execute(
      "SELECT id, titel, datum_uhrzeit, beschreibung FROM termine ORDER BY id"
      " ASC"
  )
  rows = cursor.fetchall()
  conn.close()

  embed = discord.Embed(
      title="📅 Gang-Kalender & Termine",
      description="Hier findest du alle anstehenden Gang-Termine und Events.\n\n",
      color=discord.Color.from_rgb(52, 152, 219),
  )

  if not rows:
    embed.description += "Aktuell stehen keine Termine an."
  else:
    for t_id, titel, datum_uhrzeit, beschreibung in rows:
      embed.add_field(
          name=f"📌 ID #{t_id} | {titel}",
          value=(
              f"🗓️ **Wann:** {datum_uhrzeit}\n📝 **Info:**"
              f" {beschreibung}"
          ),
          inline=False,
      )

  embed.set_footer(
      text=f"Stand: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
  )
  return embed


live_bestand_message = None
live_abmeldung_message = None
live_wochenabgabe_message = None
live_log_message = None
live_kalender_message = None


# --- AUFSTELLUNG ---
class AufstellungData:

  def __init__(self, thema, datum_zeit, rolle_mention):
    self.thema = thema
    self.datum_zeit = datum_zeit
    self.rolle = rolle_mention
    self.komme = set()
    self.komme_nicht = set()
    self.komme_spaeter = set()

  def build_embed(self):
    conn = sqlite3.connect("lager.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username, zeitraum FROM abmeldungen")
    abgemeldete_rows = cursor.fetchall()
    conn.close()

    embed = discord.Embed(
        title="Tägliche Aufstellung",
        description=f"**{self.datum_zeit}**\n\n**Thema:** {self.thema}\n**Rolle:** {self.rolle}",
        color=discord.Color.from_rgb(46, 204, 113),
    )

    komme_str = (
        "\n".join([f"• {u}" for u in self.komme]) if self.komme else "Keine"
    )
    nicht_str = (
        "\n".join([f"• {u}" for u in self.komme_nicht])
        if self.komme_nicht
        else "Keine"
    )
    spaeter_str = (
        "\n".join([f"• {u}" for u in self.komme_spaeter])
        if self.komme_spaeter
        else "Keine"
    )

    if not abgemeldete_rows:
      abgemeldet_str = "Keine"
    else:
      abgemeldet_str = ""
      for row in abgemeldete_rows:
        abgemeldet_str += f"• **{row[0]}** (Zeitraum: {row[1]})\n"

    embed.add_field(
        name=f"Komme ({len(self.komme)})", value=komme_str, inline=False
    )
    embed.add_field(
        name=f"Komme nicht ({len(self.komme_nicht)})",
        value=nicht_str,
        inline=False,
    )
    embed.add_field(
        name=f"Komme später ({len(self.komme_spaeter)})",
        value=spaeter_str,
        inline=False,
    )
    embed.add_field(
        name="Aktive Abmeldungen an diesem Tag",
        value=abgemeldet_str,
        inline=False,
    )

    embed.set_footer(
        text=f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    return embed


class AufstellungView(discord.ui.View):

  def __init__(self, data: AufstellungData):
    super().__init__(timeout=None)
    self.data = data

  async def update_attendance(
      self, interaction: discord.Interaction, status: str
  ):
    user_mention = interaction.user.mention
    self.data.komme.discard(user_mention)
    self.data.komme_nicht.discard(user_mention)
    self.data.komme_spaeter.discard(user_mention)

    if status == "komme":
      self.data.komme.add(user_mention)
      msg = "Du hast zugesagt (Komme)! ✅"
    elif status == "nicht":
      self.data.komme_nicht.add(user_mention)
      msg = "Du hast abgesagt (Komme nicht)! ❌"
    elif status == "spaeter":
      self.data.komme_spaeter.add(user_mention)
      msg = "Du hast angegeben, dass du später kommst! ⏳"

    await interaction.message.edit(embed=self.data.build_embed())
    await interaction.response.send_message(msg, ephemeral=True)

  @discord.ui.button(
      label="Komme", style=discord.ButtonStyle.green, custom_id="btn_komme"
  )
  async def komme(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await self.update_attendance(interaction, "komme")

  @discord.ui.button(
      label="Komme nicht", style=discord.ButtonStyle.red, custom_id="btn_nicht"
  )
  async def nicht(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await self.update_attendance(interaction, "nicht")

  @discord.ui.button(
      label="Komme später",
      style=discord.ButtonStyle.secondary,
      custom_id="btn_spaeter",
  )
  async def spaeter(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await self.update_attendance(interaction, "spaeter")


# --- MODALS ---
class AbmeldungEinreichenModal(discord.ui.Modal, title="Abmeldung einreichen"):
  zeitraum = discord.ui.TextInput(
      label="Zeitraum (TT.MM.JJJJ - TT.MM.JJJJ)",
      placeholder="z.B. 15.10.2026 - 20.10.2026",
  )
  grund = discord.ui.TextInput(
      label="Grund", placeholder="z.B. Urlaub / Familienfeier"
  )

  async def on_submit(self, interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    username = interaction.user.display_name

    conn = sqlite3.connect("lager.db")
    cursor = conn.cursor()
    cursor.execute(
        "REPLACE INTO abmeldungen (user_id, username, zeitraum, grund) VALUES"
        " (?, ?, ?, ?)",
        (user_id, username, self.zeitraum.value, self.grund.value),
    )
    conn.commit()
    conn.close()

    log_action(
        "Abmeldung",
        f"Zeitraum: {self.zeitraum.value} | Grund: {self.grund.value}",
        username,
    )

    global live_abmeldung_message
    if live_abmeldung_message:
      try:
        await live_abmeldung_message.edit(embed=get_abmeldungen_embed())
      except Exception:
        pass

    await interaction.response.send_message(
        "✅ Deine Abmeldung wurde erfolgreich eingereicht!", ephemeral=True
    )


class EinlagernModal(discord.ui.Modal, title="Item einlagern"):
  item_name = discord.ui.TextInput(
      label="Item-Name", placeholder="z.B. Schalldämpfer"
  )
  amount = discord.ui.TextInput(label="Menge", placeholder="z.B. 10")

  async def on_submit(self, interaction: discord.Interaction):
    try:
      qty = int(self.amount.value)
    except ValueError:
      await interaction.response.send_message(
          "❌ Die Menge muss eine Zahl sein!", ephemeral=True
      )
      return

    name = self.item_name.value.strip()
    conn = sqlite3.connect("lager.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT quantity, min_quantity FROM items WHERE name = ?", (name,)
    )
    row = cursor.fetchone()

    if row:
      new_qty = row[0] + qty
      cursor.execute(
          "UPDATE items SET quantity = ? WHERE name = ?", (new_qty, name)
      )
    else:
      cursor.execute(
          "INSERT INTO items (name, quantity, min_quantity) VALUES (?, ?, ?)",
          (name, qty, 10),
      )
    conn.commit()
    conn.close()

    log_action("Einlagern", f"{qty}x {name}", interaction.user.display_name)

    global live_bestand_message
    if live_bestand_message:
      try:
        await live_bestand_message.edit(embed=get_bestand_embed())
      except Exception:
        pass

    await interaction.response.send_message(
        f"✅ Erfolgreich **{qty}x {name}** eingelagert!", ephemeral=True
    )


class AuslagernModal(discord.ui.Modal, title="Item auslagern"):
  item_name = discord.ui.TextInput(
      label="Item-Name", placeholder="z.B. Schalldämpfer"
  )
  amount = discord.ui.TextInput(label="Menge", placeholder="z.B. 5")
  reason = discord.ui.TextInput(
      label="Verwendungszweck", placeholder="z.B. Gangwar"
  )

  async def on_submit(self, interaction: discord.Interaction):
    try:
      qty = int(self.amount.value)
    except ValueError:
      await interaction.response.send_message(
          "❌ Die Menge muss eine Zahl sein!", ephemeral=True
      )
      return

    name = self.item_name.value.strip()
    conn = sqlite3.connect("lager.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT quantity, min_quantity FROM items WHERE name = ?", (name,)
    )
    row = cursor.fetchone()

    if not row or row[0] < qty:
      conn.close()
      await interaction.response.send_message(
          "❌ Nicht genügend auf Lager oder Item existiert nicht!",
          ephemeral=True,
      )
      return

    new_qty = row[0] - qty
    cursor.execute(
        "UPDATE items SET quantity = ? WHERE name = ?", (new_qty, name)
    )
    conn.commit()
    conn.close()

    log_action(
        "Auslagern",
        f"{qty}x {name} (Grund: {self.reason.value})",
        interaction.user.display_name,
    )

    global live_bestand_message
    if live_bestand_message:
      try:
        await live_bestand_message.edit(embed=get_bestand_embed())
      except Exception:
        pass

    await interaction.response.send_message(
        f"✅ Erfolgreich **{qty}x {name}** ausgelagert!", ephemeral=True
    )


class VerifizierungModal(discord.ui.Modal, title="Server Verifizierung"):
  ic_name = discord.ui.TextInput(
      label="Dein IC-Name (Vorname Nachname)",
      placeholder="z.B. John Doe",
      required=True,
  )

  async def on_submit(self, interaction: discord.Interaction):
    name = self.ic_name.value.strip()
    guild = interaction.guild
    role = discord.utils.get(guild.roles, name="CSG")

    if not role:
      await interaction.response.send_message(
          "❌ Die Rolle **CSG** existiert nicht!", ephemeral=True
      )
      return

    try:
      await interaction.user.add_roles(role)
      try:
        await interaction.user.edit(nick=name)
      except Exception:
        pass

      log_action("Verifizierung", f"IC-Name: {name}", interaction.user.name)

      await interaction.response.send_message(
          f"✅ Verifiziert als **{name}**!", ephemeral=True
      )
    except Exception:
      await interaction.response.send_message(
          "❌ Fehler beim Zuweisen der Rolle.", ephemeral=True
      )


class AbgabeEintragenModal(discord.ui.Modal, title="Wochenabgabe eintragen"):
  member_name = discord.ui.TextInput(
      label="Mitglied (Name)", placeholder="z.B. John Doe"
  )
  status_wahl = discord.ui.TextInput(
      label="Status (abgegeben / offen / befreit)", placeholder="z.B. abgegeben"
  )

  async def on_submit(self, interaction: discord.Interaction):
    name = self.member_name.value.strip()
    status_input = self.status_wahl.value.strip().lower()

    if status_input not in ["abgegeben", "offen", "befreit"]:
      await interaction.response.send_message(
          "❌ Ungültiger Status! Nutze: `abgegeben`, `offen` oder `befreit`.",
          ephemeral=True,
      )
      return

    conn = sqlite3.connect("lager.db")
    cursor = conn.cursor()
    cursor.execute(
        "REPLACE INTO wochenabgabe (user_id, username, status) VALUES (?, ?,"
        " ?)",
        (name, name, status_input),
    )
    conn.commit()
    conn.close()

    log_action(
        "Wochenabgabe (Manuell)",
        f"User: {name} -> {status_input}",
        interaction.user.display_name,
    )

    global live_wochenabgabe_message
    if live_wochenabgabe_message:
      try:
        await live_wochenabgabe_message.edit(embed=get_wochenabgabe_embed())
      except Exception:
        pass

    await interaction.response.send_message(
        f"✅ Wochenabgabe für **{name}** auf **{status_input}** aktualisiert!",
        ephemeral=True,
    )


# NEU: MODAL UM EINEN WOCHENABGABE-EINTRAG ZU LÖSCHEN / WIDERRUFEN
class AbgabeWiderrufenModal(discord.ui.Modal, title="Wochenabgabe widerrufen"):
  member_name = discord.ui.TextInput(
      label="Mitglied (Name)", placeholder="z.B. John Doe"
  )

  async def on_submit(self, interaction: discord.Interaction):
    name = self.member_name.value.strip()

    conn = sqlite3.connect("lager.db")
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM wochenabgabe WHERE username = ? OR user_id = ?",
        (name, name),
    )
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    if deleted > 0:
      log_action(
          "Wochenabgabe Widerrufen",
          f"Eintrag für {name} gelöscht",
          interaction.user.display_name,
      )
      global live_wochenabgabe_message
      if live_wochenabgabe_message:
        try:
          await live_wochenabgabe_message.edit(embed=get_wochenabgabe_embed())
        except Exception:
          pass

      await interaction.response.send_message(
          f"✅ Der Eintrag für **{name}** wurde erfolgreich widerrufen/gelöscht!",
          ephemeral=True,
      )
    else:
      await interaction.response.send_message(
          f"❌ Es wurde kein aktiver Eintrag für **{name}** gefunden.",
          ephemeral=True,
      )


# --- PERSISTENTE VIEWS ---
class LagerView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  @discord.ui.button(
      label="Einlagern",
      style=discord.ButtonStyle.green,
      emoji="📥",
      custom_id="btn_lager_einlagern",
  )
  async def einlagern(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(EinlagernModal())

  @discord.ui.button(
      label="Auslagern",
      style=discord.ButtonStyle.red,
      emoji="📤",
      custom_id="btn_lager_auslagern",
  )
  async def auslagern(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(AuslagernModal())

  @discord.ui.button(
      label="Bestand",
      style=discord.ButtonStyle.secondary,
      emoji="📦",
      custom_id="btn_lager_bestand",
  )
  async def bestand(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_message(
        embed=get_bestand_embed(), ephemeral=True
    )


class VerifizierungView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  @discord.ui.button(
      label="Verifizieren",
      style=discord.ButtonStyle.green,
      emoji="✅",
      custom_id="btn_verifizieren",
  )
  async def verifizieren(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(VerifizierungModal())


class AbmeldungView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  @discord.ui.button(
      label="Abmeldung einreichen",
      style=discord.ButtonStyle.green,
      custom_id="btn_abmeldung_einreichen",
  )
  async def einreichen(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(AbmeldungEinreichenModal())

  @discord.ui.button(
      label="Abmeldung löschen",
      style=discord.ButtonStyle.red,
      custom_id="btn_abmeldung_loeschen",
  )
  async def loeschen(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user_id = str(interaction.user.id)
    username = interaction.user.display_name
    conn = sqlite3.connect("lager.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM abmeldungen WHERE user_id = ?", (user_id,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    if deleted > 0:
      log_action("Abmeldung gelöscht", "Vorzeitig zurückgemeldet", username)

    global live_abmeldung_message
    if live_abmeldung_message:
      try:
        await live_abmeldung_message.edit(embed=get_abmeldungen_embed())
      except Exception:
        pass

    if deleted > 0:
      await interaction.response.send_message(
          "✅ Deine Abmeldung wurde erfolgreich gelöscht (zurückgemeldet)!",
          ephemeral=True,
      )
    else:
      await interaction.response.send_message(
          "❌ Du hast aktuell keine aktive Abmeldung.", ephemeral=True
      )


class WochenabgabeView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  @discord.ui.button(
      label="Abgabe eintragen",
      style=discord.ButtonStyle.green,
      custom_id="btn_abgabe_eintragen",
  )
  async def abgabe_eintragen(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(AbgabeEintragenModal())

  @discord.ui.button(
      label="Rückgängig",
      style=discord.ButtonStyle.red,
      custom_id="btn_wochenabgabe_rueckgaengig",
  )
  async def rueckgaengig(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(AbgabeWiderrufenModal())

  @discord.ui.button(
      label="Mein Status",
      style=discord.ButtonStyle.blurple,
      custom_id="btn_mein_status",
  )
  async def mein_status(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user_id = str(interaction.user.id)
    username = interaction.user.display_name
    conn = sqlite3.connect("lager.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT status FROM wochenabgabe WHERE user_id = ? OR username = ?",
        (user_id, username),
    )
    row = cursor.fetchone()
    conn.close()

    if row:
      status_map = {
          "abgegeben": "Abgegeben ✅",
          "offen": "Offen ❌",
          "befreit": "Befreit 🟦",
      }
      status_text = status_map.get(row[0], row[0])
      await interaction.response.send_message(
          f"ℹ️ Dein aktueller Status für die Wochenabgabe: **{status_text}**",
          ephemeral=True,
      )
    else:
      await interaction.response.send_message(
          "ℹ️ Dein Status: **Offen ❌**", ephemeral=True
      )


# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


@tasks.loop(time=UHRZEIT_POST)
async def tages_aufstellung_task():
  channel = bot.get_channel(AUFSTELLUNG_KANAL_ID)
  if not channel:
    return

  guild = channel.guild
  role = discord.utils.get(guild.roles, name=ROLLE_NAME)
  role_mention = role.mention if role else "@everyone"

  heute_datum = datetime.now().strftime("%d.%m.%Y")
  datum_text = f"Heute ({heute_datum}) um 20:00 Uhr"

  data = AufstellungData(
      thema="Tägliche Gang-Aufstellung",
      datum_zeit=datum_text,
      rolle_mention=role_mention,
  )
  view = AufstellungView(data)

  await channel.send(
      content=f"{role_mention} Neue Aufstellung für heute!",
      embed=data.build_embed(),
      view=view,
  )


@bot.event
async def on_ready():
  bot.add_view(LagerView())
  bot.add_view(VerifizierungView())
  bot.add_view(AbmeldungView())
  bot.add_view(WochenabgabeView())

  try:
    synced = await bot.tree.sync()
    print(f"Synced {len(synced)} slash commands.")
  except Exception as e:
    print(e)

  if not tages_aufstellung_task.is_running():
    tages_aufstellung_task.start()

  print(f"Eingeloggt als {bot.user}")


# --- COMMANDS ---
@bot.tree.command(
    name="lagerpanel", description="Sendet das Lager-Verwaltungspanel"
)
@app_commands.checks.has_permissions(administrator=True)
async def lagerpanel(interaction: discord.Interaction):
  embed = discord.Embed(
      title="Lagerverwaltung",
      description=(
          "Lagere Items über die Buttons ein oder aus. Jede Buchung wird"
          " protokolliert."
      ),
      color=discord.Color.from_rgb(230, 126, 34),
  )
  await interaction.channel.send(embed=embed, view=LagerView())
  await interaction.response.send_message(
      "Panel wurde erfolgreich erstellt!", ephemeral=True
  )


@bot.tree.command(
    name="bestandskanal",
    description="Erstellt eine Live-Bestandsanzeige in diesem Kanal",
)
@app_commands.checks.has_permissions(administrator=True)
async def bestandskanal(interaction: discord.Interaction):
  global live_bestand_message
  live_bestand_message = await interaction.channel.send(
      embed=get_bestand_embed()
  )
  await interaction.response.send_message(
      "Live-Bestand erfolgreich eingerichtet!", ephemeral=True
  )


@bot.tree.command(
    name="verifizierung", description="Sendet das Verifizierungs-Panel"
)
@app_commands.checks.has_permissions(administrator=True)
async def verifizierung(interaction: discord.Interaction):
  embed = discord.Embed(
      title="Verifizierung",
      description=(
          "Klicke auf **Verifizieren** und gib deinen IC-Namen an, um Zugriff"
          " auf den Server zu erhalten."
      ),
      color=discord.Color.from_rgb(46, 204, 113),
  )
  await interaction.channel.send(embed=embed, view=VerifizierungView())
  await interaction.response.send_message(
      "Verifizierungs-Panel wurde gesendet!", ephemeral=True
  )


@bot.tree.command(
    name="abmeldungszentrum", description="Sendet das Abmeldungs-Panel"
)
@app_commands.checks.has_permissions(administrator=True)
async def abmeldungszentrum(interaction: discord.Interaction):
  embed = discord.Embed(
      title="Abmeldungszentrum",
      description=(
          "Reiche hier deine Abmeldung ein oder verwalte sie direkt per"
          " Button."
      ),
      color=discord.Color.from_rgb(46, 204, 113),
  )
  await interaction.channel.send(embed=embed, view=AbmeldungView())
  await interaction.response.send_message(
      "Abmeldungszentrum wurde gesendet!", ephemeral=True
  )


@bot.tree.command(
    name="abmeldungsliste",
    description="Erstellt eine Live-Anzeige aller aktiven Abmeldungen",
)
@app_commands.checks.has_permissions(administrator=True)
async def abmeldungsliste(interaction: discord.Interaction):
  global live_abmeldung_message
  live_abmeldung_message = await interaction.channel.send(
      embed=get_abmeldungen_embed()
  )
  await interaction.response.send_message(
      "Live-Abmeldungsliste eingerichtet!", ephemeral=True
  )


@bot.tree.command(
    name="wochenabgabe", description="Sendet das Wochenabgabe-Panel"
)
@app_commands.checks.has_permissions(administrator=True)
async def wochenabgabe(interaction: discord.Interaction):
  global live_wochenabgabe_message
  live_wochenabgabe_message = await interaction.channel.send(
      embed=get_wochenabgabe_embed(), view=WochenabgabeView()
  )
  await interaction.response.send_message(
      "Wochenabgabe-Panel wurde erfolgreich erstellt!", ephemeral=True
  )


@bot.tree.command(
    name="logpanel",
    description="Erstellt ein Live-Log-Panel für alle Bot-Aktivitäten",
)
@app_commands.checks.has_permissions(administrator=True)
async def logpanel(interaction: discord.Interaction):
  await interaction.response.defer(ephemeral=True)
  global live_log_message
  live_log_message = await interaction.channel.send(embed=get_log_embed())
  await interaction.followup.send(
      "Live-Log-Panel wurde erfolgreich erstellt!", ephemeral=True
  )


@bot.tree.command(
    name="kalender", description="Postet das Live-Kalender-Panel"
)
@app_commands.checks.has_permissions(administrator=True)
async def kalender(interaction: discord.Interaction):
  global live_kalender_message
  live_kalender_message = await interaction.channel.send(
      embed=get_kalender_embed()
  )
  await interaction.response.send_message(
      "Live-Kalender erfolgreich gepostet!", ephemeral=True
  )


@bot.tree.command(
    name="termin_erstellen", description="Fügt einen neuen Termin hinzu"
)
@app_commands.checks.has_permissions(administrator=True)
async def termin_erstellen(
    interaction: discord.Interaction,
    titel: str,
    datum_uhrzeit: str,
    beschreibung: str,
):
  conn = sqlite3.connect("lager.db")
  cursor = conn.cursor()
  cursor.execute(
      "INSERT INTO termine (titel, datum_uhrzeit, beschreibung, erstellt_von)"
      " VALUES (?, ?, ?, ?)",
      (titel, datum_uhrzeit, beschreibung, interaction.user.display_name),
  )
  conn.commit()
  conn.close()

  log_action(
      "Termin erstellt",
      f"{titel} am {datum_uhrzeit}",
      interaction.user.display_name,
  )

  global live_kalender_message
  if live_kalender_message:
    try:
      await live_kalender_message.edit(embed=get_kalender_embed())
    except Exception:
      pass

  await interaction.response.send_message(
      f"✅ Termin **{titel}** für **{datum_uhrzeit}** wurde im Kalender"
      " eingetragen!",
      ephemeral=True,
  )


@bot.tree.command(
    name="termin_loeschen", description="Löscht einen Termin anhand der ID"
)
@app_commands.checks.has_permissions(administrator=True)
async def termin_loeschen(interaction: discord.Interaction, termin_id: int):
  conn = sqlite3.connect("lager.db")
  cursor = conn.cursor()
  cursor.execute("DELETE FROM termine WHERE id = ?", (termin_id,))
  deleted = cursor.rowcount
  conn.commit()
  conn.close()

  if deleted > 0:
    log_action(
        "Termin gelöscht",
        f"ID #{termin_id}",
        interaction.user.display_name,
    )
    global live_kalender_message
    if live_kalender_message:
      try:
        await live_kalender_message.edit(embed=get_kalender_embed())
      except Exception:
        pass
    await interaction.response.send_message(
        f"✅ Termin ID #{termin_id} wurde erfolgreich gelöscht!",
        ephemeral=True,
    )
  else:
    await interaction.response.send_message(
        f"❌ Es wurde kein Termin mit der ID #{termin_id} gefunden.",
        ephemeral=True,
    )


@bot.tree.command(
    name="setzwert", description="Ändert den geforderten Betrag der Wochenabgabe"
)
@app_commands.checks.has_permissions(administrator=True)
async def setzwert(interaction: discord.Interaction, betrag: int):
  conn = sqlite3.connect("lager.db")
  cursor = conn.cursor()
  cursor.execute(
      "REPLACE INTO einstellungen (key, value) VALUES ('wochenabgabe_betrag', ?)",
      (str(betrag),),
  )
  conn.commit()
  conn.close()

  log_action(
      "Einstellungen",
      f"Wochenabgabe-Betrag auf {betrag:,}$ gesetzt",
      interaction.user.display_name,
  )

  global live_wochenabgabe_message
  if live_wochenabgabe_message:
    try:
      await live_wochenabgabe_message.edit(embed=get_wochenabgabe_embed())
    except Exception:
      pass

  await interaction.response.send_message(
      f"✅ Der Wochenabgabe-Betrag wurde erfolgreich auf **{betrag:,}$**"
      " geändert!",
      ephemeral=True,
  )


@bot.tree.command(
    name="aufstellung", description="Manuelle Aufstellung senden"
)
@app_commands.checks.has_permissions(administrator=True)
async def aufstellung(
    interaction: discord.Interaction,
    thema: str,
    datum_zeit: str,
    rolle: discord.Role,
):
  data = AufstellungData(
      thema=thema, datum_zeit=datum_zeit, rolle_mention=rolle.mention
  )
  view = AufstellungView(data)

  await interaction.channel.send(
      content=f"{rolle.mention} Neue Aufstellung: **{thema}**",
      embed=data.build_embed(),
      view=view,
  )
  log_action(
      "Aufstellung",
      f"Thema: {thema} ({datum_zeit})",
      interaction.user.display_name,
  )
  await interaction.response.send_message(
      "Aufstellung gesendet!", ephemeral=True
  )

import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# --- MINI-WEBSERVER FÜR RENDER (Kostenloser Web-Service Port-Fix) ---
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"CSG Bot is online!")

def run_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

# Server in einem separaten Hintergrund-Thread starten, damit der Bot nicht blockiert wird
threading.Thread(target=run_server, daemon=True).start()

# --- BOT STARTEN ---
TOKEN = os.getenv("DISCORD_TOKEN") or "MTU1OTkzNjMwOTYwOTM3Mzc5Nw.GM5WVp.mavqPTSvz82it8voW4Rtd4Of-z_evGgyNDWizQ"
bot.run(TOKEN)
