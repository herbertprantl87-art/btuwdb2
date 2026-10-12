// Browser-Tests: Registrierung und Anmeldung einmal komplett durchspielen.
// Die Datenbank ist nachgebaut (nachbau.mjs), die echte Supabase wird nie angefragt.
import { test, expect } from "@playwright/test";
import { seiteMitNachbau, SEITE, hash } from "./nachbau.mjs";

const profil = (db, id) => db.profiles.find(p => p.id === id);

async function benutzername(page, name) {
  await page.goto(SEITE);
  await page.getByPlaceholder("Benutzername").fill(name);
  await page.getByRole("button", { name: "Weiter →" }).click();
}

async function menuHat(page, text) {
  await page.locator('[title="Menü"]').click();
  return page.getByText(text, { exact: true }).isVisible();
}

test("Neue Mitarbeiterin: Konto erst möglich, wenn Gebiet, Vorname und Passwort stimmen", async ({ page }) => {
  const db = await seiteMitNachbau(page);
  await benutzername(page, "lisa test");

  const knopf = page.getByRole("button", { name: "Konto erstellen →" });
  await expect(knopf).toBeDisabled();
  await expect(page.getByText(/Noch offen: Gebiet, Vorname/)).toBeVisible();

  await page.locator('select:has(option[value="Berlin-Alem"])').selectOption("Berlin-Alem");
  await expect(knopf).toBeDisabled();
  await page.getByPlaceholder("Dein Vorname").fill("Lisa");
  await page.getByPlaceholder("Passwort (mind. 4 Zeichen)").fill("test1234");
  await page.getByPlaceholder("Passwort wiederholen").fill("anders");
  await expect(knopf).toBeDisabled();
  await page.getByPlaceholder("Passwort wiederholen").fill("test1234");
  await expect(knopf).toBeEnabled();
  await knopf.click();

  await expect.poll(() => profil(db, "lisa test")?.gebiet).toBe("Berlin-Alem");
  expect(profil(db, "lisa test").role).toBe("mitarbeiter");
  expect(await menuHat(page, "📊 Auswertung")).toBe(false);
});

test("Normale Anmeldung mit Bayern-Gebiet bleibt Mitarbeiter (gleicher Wert wie GL-Gebiet)", async ({ page }) => {
  const db = await seiteMitNachbau(page);
  await benutzername(page, "jakob test");
  await page.locator('select:has(option[value="Bayern-Szabolcs"])').selectOption("Bayern-Szabolcs");
  await page.getByPlaceholder("Dein Vorname").fill("Jakob");
  await page.getByPlaceholder("Passwort (mind. 4 Zeichen)").fill("test1234");
  await page.getByPlaceholder("Passwort wiederholen").fill("test1234");
  await page.getByRole("button", { name: "Konto erstellen →" }).click();

  await expect.poll(() => profil(db, "jakob test")?.role).toBe("mitarbeiter");
  expect(await menuHat(page, "📊 Auswertung")).toBe(false);
});

test("GL-Anmeldung über das Logo ergibt GL-Rechte (Szabi-Fall)", async ({ page }) => {
  const db = await seiteMitNachbau(page);
  await page.goto(SEITE);
  const logo = page.locator('[data-test="login-logo"]');
  await logo.click(); await logo.click(); await logo.click();
  await page.getByPlaceholder("Benutzername").fill("szabi test");
  await page.getByRole("button", { name: "Weiter →" }).click();
  await page.locator('select:has(option[value="Bayern-Szabolcs"])').selectOption("Bayern-Szabolcs");
  await page.getByPlaceholder("Passwort (mind. 4 Zeichen)").fill("test1234");
  await page.getByPlaceholder("Passwort wiederholen").fill("test1234");
  await page.getByRole("button", { name: "Konto erstellen →" }).click();

  await expect.poll(() => profil(db, "szabi test")?.role).toBe("gebietsleiter");
  expect(profil(db, "szabi test").gebiet).toBe("Bayern-Szabolcs");
  expect(await menuHat(page, "📊 Auswertung")).toBe(true);
});

test("Bestehendes Konto ohne Gebiet muss erst vervollständigt werden", async ({ page }) => {
  const db = await seiteMitNachbau(page, {
    app_config: [{ key: "auth_user__patrick test", value: { hash: hash("test1234") } }],
    profiles: [{ id: "patrick test", name: "patrick test", first_name: "patrick test", gebiet: "", role: "mitarbeiter" }],
  });
  await benutzername(page, "patrick test");
  await page.getByPlaceholder("Passwort").fill("test1234");
  await page.getByPlaceholder("Passwort").press("Enter");

  await expect(page.getByText("Angaben vervollständigen")).toBeVisible();
  const weiter = page.getByRole("button", { name: "Weiter →" });
  await expect(weiter).toBeDisabled();
  await page.locator('select:has(option[value="Berlin-Alem"])').selectOption("Berlin-Alem");
  await expect(weiter).toBeDisabled();
  await page.getByPlaceholder("Dein Vorname").fill("Patrick");
  await expect(weiter).toBeEnabled();
  await weiter.click();

  await expect.poll(() => profil(db, "patrick test")?.gebiet).toBe("Berlin-Alem");
  expect(profil(db, "patrick test").role).toBe("mitarbeiter");
});

test("Rolle kommt beim Login aus der Datenbank, nicht aus dem Gebiet", async ({ page }) => {
  const db = await seiteMitNachbau(page, {
    app_config: [{ key: "auth_user__maria test", value: { hash: hash("test1234") } }],
    profiles: [{ id: "maria test", name: "Maria", first_name: "Maria", gebiet: "Berlin-Alem", role: null }],
  });
  await benutzername(page, "maria test");
  await page.getByPlaceholder("Passwort").fill("test1234");
  await page.getByPlaceholder("Passwort").press("Enter");

  await expect.poll(() => profil(db, "maria test")?.role).toBe("mitarbeiter");
  expect(await menuHat(page, "📊 Auswertung")).toBe(false);
});
