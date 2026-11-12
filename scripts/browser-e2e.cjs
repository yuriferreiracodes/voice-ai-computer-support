// Browser end-to-end test: real Chromium, fake microphone fed from a WAV file.
// Exercises getUserMedia -> AudioWorklet -> VAD -> WebSocket -> backend -> OpenRouter -> playback -> UI.
//
//   npm i playwright && npx playwright install chromium
//   node scripts/browser-e2e.cjs <speech.wav> [http://localhost:3000]
//
// The WAV should contain silence, then speech, then a few seconds of silence (Chrome loops it).
const path = require("path");
const { chromium } = require("playwright");

const wav = path.resolve(process.argv[2] || "scripts/out/fake-mic.wav");
const url = process.argv[3] || "http://localhost:3000";
const shots = path.resolve(process.env.SHOT_DIR || "scripts/out");

(async () => {
  const browser = await chromium.launch({
    args: [
      "--use-fake-ui-for-media-stream", // auto-accept the microphone prompt
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-audio-capture=${wav}`,
      "--autoplay-policy=no-user-gesture-required",
    ],
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  const consoleErrors = [];
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  const step = async (name, fn) => {
    const t = Date.now();
    await fn();
    console.log(`ok  ${name} (${Date.now() - t} ms)`);
  };
  const conversation = page.getByRole("list", { name: "Conversation" });
  const assistantCount = () => conversation.locator('li[data-role="assistant"]').count();
  const waitForAssistant = (n, timeout = 30000) =>
    page.waitForFunction(
      (k) => document.querySelectorAll('[aria-label="Conversation"] li[data-role="assistant"]').length >= k,
      n,
      { timeout },
    );

  try {
    await page.goto(url);
    await step("Start Call button visible", () => page.getByRole("button", { name: "Start Call" }).waitFor());
    await page.screenshot({ path: `${shots}/ui-idle.png` });

    await page.getByRole("button", { name: "Start Call" }).click();
    await step("connected", () => page.getByRole("status").filter({ hasText: "Connected" }).waitFor({ timeout: 15000 }));
    await step("AI greeting shown", () =>
      conversation.getByText("Support AI").first().waitFor({ timeout: 30000 }),
    );
    await step("user speech captured, sent and transcribed", () =>
      conversation.getByText("You", { exact: true }).first().waitFor({ timeout: 45000 }),
    );
    await step("AI answered the spoken turn", () => waitForAssistant(2));

    await step("mute / unmute", async () => {
      await page.getByRole("button", { name: "Mute" }).click();
      await page.getByText("Microphone muted").waitFor();
      await page.getByRole("button", { name: "Unmute" }).click();
    });

    await step("typed message gets a reply", async () => {
      await page.getByRole("button", { name: "Mute" }).click(); // stop the looping fake mic interfering
      await page.waitForTimeout(1500); // let any in-flight voice turn finish
      const before = await assistantCount();
      await page.getByLabel("Type a message").fill("It says error 0x80070005");
      await page.getByRole("button", { name: "Send" }).click();
      await conversation.getByText("You (typed)").waitFor();
      await waitForAssistant(before + 1);
    });

    await step("screenshot upload gets analysed", async () => {
      const before = await assistantCount();
      await page.locator('input[type="file"]').setInputFiles(`${shots}/ui-idle.png`);
      await conversation.getByText("You (screenshot)").waitFor({ timeout: 15000 });
      await conversation.getByRole("img", { name: "Uploaded screenshot" }).waitFor();
      await waitForAssistant(before + 1, 60000);
    });

    await page.screenshot({ path: `${shots}/ui-call.png` });
    await step("end call", async () => {
      await page.getByRole("button", { name: "End call" }).click();
      await page.getByText("Call ended").waitFor();
      await page.getByRole("status").filter({ hasText: "Offline" }).waitFor();
    });

    const transcript = await conversation.locator("li").allInnerTexts();
    console.log("\nTranscript:\n" + transcript.filter(Boolean).map((t) => "  " + t.replace(/\n/g, ": ")).join("\n"));
    if (consoleErrors.length) console.log("\nConsole errors:\n  " + consoleErrors.join("\n  "));
    console.log(`\nPASS  (screenshots in ${shots})`);
  } catch (e) {
    await page.screenshot({ path: `${shots}/ui-failure.png` }).catch(() => {});
    console.error("\nFAIL:", e.message, "\nConsole errors:", consoleErrors);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
