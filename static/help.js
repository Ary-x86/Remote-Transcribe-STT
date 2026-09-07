// Content for the "?" modal. Figures are from Groq's own docs, checked
// 2026-09-06 — see console.groq.com/docs/speech-to-text.
window.HELP = {

usage: `
<h3>Getting set up</h3>
<ol>
  <li>Create an API key at <a href="https://console.groq.com/keys" target="_blank" rel="noopener">console.groq.com/keys</a>.</li>
  <li>Copy <span class="pill">.env.example</span> to <span class="pill">.env</span> next to the app.</li>
  <li>Put the key on the <span class="pill">GROQ_API_KEY</span> line and restart.</li>
</ol>
<p>The key stays on the server. It is never sent to your browser, and it is not stored in the database.</p>

<h3>Recording vs uploading</h3>
<p><strong>Record</strong> captures straight from your microphone — best for dictation. <strong>Upload</strong> takes
any audio or video file; the soundtrack is extracted for you.</p>
<p>Browsers only grant microphone access on <span class="pill">localhost</span> or over HTTPS. If the record
button is disabled on a remote server, that is why — put the app behind TLS, or upload files instead.</p>

<h3>The options that actually matter</h3>
<ul>
  <li><strong>Language</strong> — naming it makes transcription faster and more accurate. Leave it on
      Auto when you are not sure, or when speakers switch between languages mid-conversation.</li>
  <li><strong>Vocabulary hints</strong> — a short list of names, jargon, and spellings Whisper keeps
      getting wrong. Write it in the same language as the audio. It is a nudge, not a rule, and
      anything past roughly 224 tokens is ignored.</li>
  <li><strong>Cleanup</strong> — an optional second pass that turns dictation into readable text.
      The raw transcript is always kept, so you can switch presets or go back to it later.</li>
  <li><strong>Temperature</strong> — leave at 0. Only raise it if the output gets stuck repeating a phrase.</li>
</ul>

<h3>Long recordings</h3>
<p>Audio is converted to 16 kHz mono FLAC, which is what Groq recommends and also shrinks it a lot.
Anything still over the upload limit is split at natural pauses, transcribed in parallel, and
stitched back together. The pieces overlap slightly so no word is lost at a seam. A two-hour
recording works; it just takes a few passes.</p>

<h3>Speakers</h3>
<p>Groq's Whisper API returns text with no idea who said what — it has no diarization at all. So
there are two options here, and they are not equivalent:</p>
<ul>
  <li><strong>Estimate with an LLM</strong> works everywhere and costs about a cent, but it reads the
      <em>transcript</em>, not the voices. It is dependable on clean back-and-forth dialogue and
      guesses badly when people talk over each other. Treat it as a draft.</li>
  <li><strong>Acoustic</strong> is real voice-based separation via ElevenLabs Scribe. It needs
      <span class="pill">ELEVENLABS_API_KEY</span> in your <span class="pill">.env</span> and costs
      about five times as much per hour. Use it when attribution has to be right.</li>
</ul>
<p>Either way you can rename speakers by clicking a label in the Speakers tab.</p>
`,

models: `
<h3>Pick a model</h3>
<div class="table-scroll">
<table>
  <tr><th>Model</th><th>Per hour</th><th>Error rate</th><th>Speed</th><th>Best for</th></tr>
  <tr>
    <td><span class="pill">whisper-large-v3-turbo</span><br><em class="muted">recommended</em></td>
    <td>$0.04</td><td>12%</td><td>216&times;</td>
    <td>The default. Almost as accurate as v3 at under half the price, and fast enough that
        dictation comes back before you have switched windows.</td>
  </tr>
  <tr>
    <td><span class="pill">whisper-large-v3</span></td>
    <td>$0.111</td><td>10.3%</td><td>189&times;</td>
    <td>The accurate one. Worth the extra when there are strong accents, background noise, a bad
        microphone, or a language other than English.</td>
  </tr>
  <tr>
    <td><span class="pill">scribe_v2</span><br><em class="muted">ElevenLabs</em></td>
    <td>$0.22</td><td>&mdash;</td><td>batch</td>
    <td>The only option here that can actually tell voices apart. Also skips the chunking step,
        since it accepts files far larger than Groq will.</td>
  </tr>
</table>
</div>
<p class="muted small">Speed is relative to realtime: 216&times; means an hour of audio comes back in
about sixteen seconds. The model list is fetched live from your account, so anything new Groq adds
shows up here automatically.</p>

<h3>Rules of thumb</h3>
<ul>
  <li><strong>Dictating a prompt?</strong> Turbo, language set, cleanup on "Format as prompt".</li>
  <li><strong>Interview or meeting?</strong> Large v3, speakers on. Use acoustic if it matters who said what.</li>
  <li><strong>Noisy or heavily accented?</strong> Large v3, and put the tricky names in vocabulary hints.</li>
  <li><strong>Foreign audio you just need the gist of?</strong> Set the task to Translate to English.</li>
</ul>

<h3>What the cleanup presets do</h3>
<ul>
  <li><strong>Raw</strong> — exactly what Whisper heard. No second call, no extra cost.</li>
  <li><strong>Clean up</strong> — drops filler and false starts, fixes punctuation and paragraphs,
      keeps your wording.</li>
  <li><strong>Format as prompt</strong> — reorganises rambling dictation into a structured prompt
      while preserving every requirement you mentioned.</li>
  <li><strong>Summary notes</strong> — condenses to key points, decisions, and action items.</li>
</ul>
`,

limits: `
<h3>What it costs</h3>
<p>Transcription is billed per hour of <em>audio</em>, not per word:</p>
<ul>
  <li>A 2-minute dictated prompt on Turbo: about <strong>$0.0013</strong>. Roughly 750 of them per dollar.</li>
  <li>A 1-hour meeting on Large v3: about <strong>$0.11</strong>.</li>
  <li>Cleanup and speaker estimation add a fraction of a cent each.</li>
</ul>
<p>Groq bills a minimum of 10 seconds per request, so very short clips cost the same as a 10-second one.</p>

<h3>Free tier limits</h3>
<div class="table-scroll">
<table>
  <tr><th>Limit</th><th>Free tier</th><th>What it means</th></tr>
  <tr><td>File size</td><td>25 MB</td><td>Larger files are split automatically</td></tr>
  <tr><td>Requests</td><td>20/min, 2000/day</td><td>Each chunk counts as one request</td></tr>
  <tr><td>Audio volume</td><td>7200 s/hour</td><td>Two hours of audio per hour</td></tr>
  <tr><td></td><td>28800 s/day</td><td>Eight hours of audio per day</td></tr>
</table>
</div>
<p>On the paid developer tier the file limit rises to 100 MB. Raise
<span class="pill">MAX_UPLOAD_BYTES</span> in your <span class="pill">.env</span> to match and the app
will split less often.</p>

<h3>Known rough edges</h3>
<ul>
  <li><strong>Mixed languages in one recording.</strong> Whisper handles one language at a time. On a
      genuinely bilingual conversation it may quietly translate everything into the dominant one.
      Leave the language on Auto, and use ElevenLabs if it keeps getting it wrong.</li>
  <li><strong>Estimated speakers are a guess</strong> read from the text, not the audio. See the
      Speakers section under "How to use".</li>
  <li><strong>Silence and music</strong> can make Whisper hallucinate a phrase or two — often a stray
      "Thank you" or a subtitle credit. Trim dead air before uploading if you see it.</li>
</ul>

<h3>Your data</h3>
<p>Transcripts and audio live in the <span class="pill">data/</span> folder on this server and nowhere
else. Audio is deleted along with its transcript, and history is pruned on the schedule set by
<span class="pill">HISTORY_RETENTION_DAYS</span>. Set <span class="pill">KEEP_AUDIO=false</span> to keep
the text but never store the recordings.</p>
`
};
