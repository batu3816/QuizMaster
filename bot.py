import discord
from discord import app_commands, ui
import os
import io
import pypdf
import json
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv
 
# --- SETUP ---
import sys

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")    
print("OPENAI-Key geladen:", OPENAI_API_KEY is not None)
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
 
# --- QUIZ LOGIK (BUTTONS) ---
class QuizView(ui.View):
    def __init__(self, questions, user):
        super().__init__(timeout=None)
        self.questions = questions
        self.user = user
        self.current_index = 0
        self.score = 0
        self.add_buttons()
 
    def add_buttons(self):
        self.clear_items()
        q = self.questions[self.current_index]
        for i, option in enumerate(q['options']):
            btn = ui.Button(label=option, custom_id=str(i), style=discord.ButtonStyle.secondary)
            btn.callback = self.check_answer
            self.add_item(btn)
 
    async def check_answer(self, interaction: discord.Interaction):
        if interaction.user != self.user:
            return await interaction.response.send_message("Das ist nicht dein Quiz!", ephemeral=True)
       
        correct_idx = int(self.questions[self.current_index]['correct'])
        if int(interaction.data['custom_id']) == correct_idx:
            self.score += 1
            await interaction.response.send_message("Richtig! ✅", ephemeral=True)
        else:
            await interaction.response.send_message(f"Falsch! ❌ Die richtige Antwort war: {self.questions[self.current_index]['options'][correct_idx]}", ephemeral=True)
 
        self.current_index += 1
        if self.current_index < len(self.questions):
            q = self.questions[self.current_index]
            self.add_buttons()
            await interaction.edit_original_response(content=f"**Frage {self.current_index+1}:** {q['q']}", view=self)
        else:
            # Quiz Ende -> Notenberechnung
            max_p = len(self.questions)
            note = (self.score / max_p) * 5 + 1
            note = round(note * 2) / 2
            await interaction.edit_original_response(content=f"🏁 **Quiz beendet!**\nErgebnis: {self.score}/{max_p}\nDeine Schweizer Note: **{note}**", view=None)
 
# --- BOT HAUPTKLASSE ---
class QuizBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
 
    async def setup_hook(self):
        await self.tree.sync()
        print("Bot-System ist vollständig bereit!")
 
bot = QuizBot()
 
# --- BEFEHLE ---
 
@bot.tree.command(name="study", description="Generiert ein Quiz aus Datei, Bild, Screenshot oder Code")
async def study(interaction: discord.Interaction, datei: discord.Attachment):
    await interaction.response.defer()

    try:
        filename = datei.filename.lower()
        file_bytes = await datei.read()
        inhalt = ""
        is_image = filename.endswith((".png", ".jpg", ".jpeg", ".webp"))

        # PDF
        if filename.endswith(".pdf"):
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    inhalt += text + "\n"

        # Word DOCX
        elif filename.endswith(".docx"):
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            for paragraph in doc.paragraphs:
                inhalt += paragraph.text + "\n"

        # Excel
        elif filename.endswith((".xlsx", ".xlsm")):
            import openpyxl
            workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            for sheet in workbook.worksheets:
                inhalt += f"\nTabelle: {sheet.title}\n"
                for row in sheet.iter_rows(values_only=True):
                    row_text = " | ".join([str(cell) for cell in row if cell is not None])
                    if row_text:
                        inhalt += row_text + "\n"

        # PowerPoint
        elif filename.endswith(".pptx"):
            from pptx import Presentation
            presentation = Presentation(io.BytesIO(file_bytes))
            for slide_number, slide in enumerate(presentation.slides, start=1):
                inhalt += f"\nFolie {slide_number}:\n"
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        inhalt += shape.text + "\n"

        # Bilder / Screenshots
        elif is_image:
            inhalt = "Analysiere dieses Bild oder diesen Screenshot und erstelle daraus ein Quiz."

        # Textdateien und Code-Dateien
        elif filename.endswith((
            ".txt", ".md", ".csv",
            ".py", ".java", ".js", ".html", ".css",
            ".sql", ".json", ".xml", ".yml", ".yaml",
            ".php", ".cs", ".cpp", ".c"
        )):
            inhalt = file_bytes.decode("utf-8", errors="ignore")

        else:
            await interaction.followup.send("❌ Dieser Dateityp wird aktuell nicht unterstützt.")
            return

        if not OPENAI_API_KEY:
            await interaction.followup.send("❌ Fehler: Kein OpenAI-Key gefunden. Bitte Key in .env eintragen!")
            return

        # OpenAI Anfrage
        if is_image:
            try:
                models = client.models.list()
                print("MODELS OK")
                print("ERSTES MODELL:", models.data[0].id)
                print("KEY ENDE:", os.getenv("OPENAI_API_KEY")[-4:])
            except Exception as e:
                print("MODELS FEHLER:", e)

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """
Erstelle genau 10 Multiple-Choice-Fragen aus dem Bild/Screenshot.
Antworte NUR als valides JSON-Objekt in diesem Format:
{
  "questions": [
    {
      "q": "Frage",
      "options": ["Antwort A", "Antwort B", "Antwort C", "Antwort D"],
      "correct": 0
    }
  ]
}
"""
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": inhalt},
                            {"type": "image_url", "image_url": {"url": datei.url}}
                        ]
                    }
                ],
                response_format={"type": "json_object"}
            )
        else:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """
Erstelle genau 10 Multiple-Choice-Fragen zum Inhalt.
Antworte NUR als valides JSON-Objekt in diesem Format:
{
  "questions": [
    {
      "q": "Frage",
      "options": ["Antwort A", "Antwort B", "Antwort C", "Antwort D"],
      "correct": 0
    }
  ]
}
"""
                    },
                    {"role": "user", "content": inhalt[:12000]}
                ],
                response_format={"type": "json_object"}
            )

        data = json.loads(response.choices[0].message.content)
        questions = data.get("questions", [])

        if not questions:
            await interaction.followup.send("❌ Es konnten keine Quizfragen erstellt werden.")
            return

        view = QuizView(questions, interaction.user)
        await interaction.followup.send(f"**Frage 1:** {questions[0]['q']}", view=view)

    except Exception as e:
        import traceback
        traceback.print_exc()
        await interaction.followup.send(f"❌ Ein Fehler ist aufgetreten: {type(e).__name__}: {e}")

@bot.tree.command(name="plan", description="Erstellt Lernplan")
async def plan(interaction: discord.Interaction, datum: str):
    try:
        ziel = datetime.strptime(datum, "%d.%m.%Y")
        tage = (ziel - datetime.now()).days
        if tage < 0: return await interaction.response.send_message("Datum in Vergangenheit!")
        minuten = 20 if tage > 14 else 45
        await interaction.response.send_message(f"📅 Prüfung am {datum} ({tage} Tage übrig). Lerne täglich {minuten} Min!")
    except:
        await interaction.response.send_message("Format: DD.MM.YYYY")
 
if __name__ == "__main__":
    bot.run(TOKEN)
 