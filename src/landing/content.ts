// All the words on the landing page live here, so they are easy to find and change.
// (The brand name and tagline live in src/brand.ts.)

import type { FeatureStatus } from '../lib/status'

export const LINES = ['Heart line', 'Head line', 'Life line', 'Fate line', 'Sun line']

export type Chip = { label: string; status?: FeatureStatus }
export type HowStep = { n: string; title: string; body: string; chips?: Chip[] }

export const HOW_STEPS: HowStep[] = [
  {
    n: '01',
    title: 'Upload both palms',
    body: 'One clear photo of your left hand and one of your right, side by side. JPG or PNG. Preview either one and swap it before anything is done with it.',
  },
  {
    n: '02',
    title: 'We check the photos',
    body: 'File type, file health, size, focus, lighting, and whether a palm is really in view. If a photo will not work, you get a plain instruction on how to retake it, never a silent failure.',
  },
  {
    n: '03',
    title: 'Six steps of image processing',
    body: 'OpenCV cleans each photo so the creases stand out, and you can see the original beside every stage.',
    chips: [
      { label: 'Grayscale' },
      { label: 'Gaussian smoothing' },
      { label: 'CLAHE contrast' },
      { label: 'Canny edges' },
      { label: 'Thresholding' },
      { label: 'Morphology' },
    ],
  },
  {
    n: '04',
    title: 'The lines, marked honestly',
    body: 'The main lines are located and drawn on your photo. Each one carries a status, and a line that cannot be seen is never invented.',
    chips: [
      { label: 'Detected', status: 'detected' },
      { label: 'Uncertain', status: 'uncertain' },
      { label: 'Not visible', status: 'not_visible' },
    ],
  },
  {
    n: '05',
    title: 'A reader that sticks to the facts',
    body: 'Only the results, never your photo, go to Gemini, an AI made by Google, together with our palmistry notes and strict rules. It predicts only from what was actually found, and every passage it writes is checked before you see it.',
  },
  {
    n: '06',
    title: 'Read, compare, then chat',
    body: 'Your reading puts your left hand beside your right and keeps what the photos show apart from what your lines predict. Then ask follow-up questions in a chat about this one reading.',
  },
]

export type Stage = { key: 'gray' | 'blur' | 'contrast' | 'edges' | 'threshold' | 'morphology'; label: string; body: string }

export const STAGES: Stage[] = [
  {
    key: 'gray',
    label: 'Grayscale',
    body: 'Colour is dropped so only brightness is left. Creases are darker than the skin around them, and one channel is far easier to work with than three.',
  },
  {
    key: 'blur',
    label: 'Gaussian smoothing',
    body: 'A gentle blur averages away sensor noise and skin texture, so tiny speckles are not mistaken for lines.',
  },
  {
    key: 'contrast',
    label: 'CLAHE contrast',
    body: 'Contrast is lifted in small tiles instead of across the whole picture, so faint creases stand out even in uneven light.',
  },
  {
    key: 'edges',
    label: 'Canny edges',
    body: 'Finds where brightness changes sharply, which traces crease-like shapes. It cannot tell a heart line from a life line, so naming them is the later stage’s job.',
  },
  {
    key: 'threshold',
    label: 'Thresholding',
    body: 'Every pixel is compared with the brightness of its own neighbourhood. Darker than its surroundings becomes white and everything else black, which leaves a plain map of crease-like marks that does not depend on how bright the whole photo is.',
  },
  {
    key: 'morphology',
    label: 'Morphology',
    body: 'Opening removes tiny specks, then closing joins the pieces of a line that a faint patch broke apart. The result is cleaner, connected shapes for the line finder to follow.',
  },
]

export const PRIVACY = [
  {
    title: 'Photos are not kept',
    body: 'Palm photos are processed in memory or temporary storage and removed after analysis, even when something fails. With an account, only the results, your report and your chats are saved.',
  },
  {
    title: 'Guest mode is temporary',
    body: 'Try the whole journey, chat included, without signing up. Nothing becomes saved history, and the session expires on its own.',
  },
  {
    title: 'Delete means delete',
    body: 'Deleting a hand profile also deletes its readings, conversations, messages and the data derived from them.',
  },
  {
    title: 'Nothing moves quietly',
    body: 'If you create an account after a guest session, we ask before importing anything. Data is never transferred silently.',
  },
  {
    title: 'One person at a time',
    body: 'Each chat belongs to one hand profile and one reading, ownership is checked on every request, and switching profile starts a fresh chat.',
  },
  {
    title: 'Ask before you upload',
    body: 'Only upload someone else’s palms with their permission, and keep profile names simple. A nickname is plenty.',
  },
]

export const FAQ = [
  {
    q: 'Do I need an account?',
    a: 'No. Guest mode runs the whole journey: upload, processing, reading and chat. It is temporary and is not saved. Create an account when you want to keep hand profiles, readings and conversations.',
  },
  {
    q: 'Why two hands?',
    a: 'In traditional palmistry the hands are read together, often described as one showing what you were born with and the other what life has shaped. The reading sets them side by side and compares them.',
  },
  {
    q: 'What makes a good photo?',
    a: 'Even daylight, palm flat and facing the camera, fingers gently apart, the whole hand in the frame and in sharp focus. Avoid shadows across the palm and harsh flash.',
  },
  {
    q: 'What happens to my photos?',
    a: 'They are checked and then thrown away, never stored for good. A saved reading keeps only the results, the report and your chat, and a simple sketch of your hand can be redrawn from those. The step that finds your hand runs on the server with MediaPipe, a tool from Google. The tool only tells Google its own version and the server’s operating system, and no photo goes with that.',
  },
  {
    q: 'What does Gemini see?',
    a: 'Only the results as words, for example “heart line: long, gentle curve”, together with our palmistry notes. Never a photo and never your name. Your chat questions go too, with names, e-mail addresses, phone numbers and links removed. Google runs Gemini, and on its free tier Google may use what it receives to improve its products, so keep private details out of the chat. Each passage Gemini writes is checked before you see it, and if one fails, the app’s own wording is used and the reading says so.',
  },
  {
    q: 'Is the reading accurate? Can it really foretell my future?',
    a: 'Palmistry is an old art, not a science, so nothing proves that a palm can predict anything: take your reading as a story about who you may become, not a promise. Your reader speaks with confidence about love, work, creativity, travel and change, but never gives dates or ages, and never speaks of health or money decisions. Finding lines in a photo is also hard, so every line is marked detected, uncertain or not visible, and the reading only speaks about what was found.',
  },
  {
    q: 'Does the AI just look at my photo and guess?',
    a: 'No. The photo steps are shown one by one so you can see them, and the AI only receives the results (which lines were found), never a made-up list of lines. What it writes is checked against those results.',
  },
  {
    q: 'How does the chat know about my reading?',
    a: 'The app, not the AI’s memory, sends the selected reading’s results, the report and the earlier messages of that chat along with every question. Switch profile or reading and a fresh chat begins.',
  },
]
