// Small, readable versions of the classic image-processing steps.
// They are used to ILLUSTRATE the pipeline in the browser (the landing-page demo, and the sample data
// shown while the app runs in mock mode). The real processing happens in OpenCV on the Python backend;
// the frontend never does the processing for a real reading.

export type Gray = { w: number; h: number; data: Uint8ClampedArray }

export function toGray(img: ImageData): Gray {
  const { width: w, height: h, data } = img
  const out = new Uint8ClampedArray(w * h)
  for (let i = 0, j = 0; i < out.length; i++, j += 4) {
    out[i] = 0.299 * data[j] + 0.587 * data[j + 1] + 0.114 * data[j + 2]
  }
  return { w, h, data: out }
}

/** Gaussian smoothing (separable kernel). */
export function gaussianBlur(g: Gray, sigma = 1.6): Gray {
  const r = Math.max(1, Math.ceil(sigma * 3))
  const k = new Float32Array(r * 2 + 1)
  let sum = 0
  for (let i = -r; i <= r; i++) {
    const v = Math.exp(-(i * i) / (2 * sigma * sigma))
    k[i + r] = v
    sum += v
  }
  for (let i = 0; i < k.length; i++) k[i] /= sum

  const { w, h, data } = g
  const tmp = new Float32Array(w * h)
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let acc = 0
      for (let i = -r; i <= r; i++) acc += data[y * w + Math.min(w - 1, Math.max(0, x + i))] * k[i + r]
      tmp[y * w + x] = acc
    }
  }
  const out = new Uint8ClampedArray(w * h)
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let acc = 0
      for (let i = -r; i <= r; i++) acc += tmp[Math.min(h - 1, Math.max(0, y + i)) * w + x] * k[i + r]
      out[y * w + x] = acc
    }
  }
  return { w, h, data: out }
}

/** CLAHE: contrast-limited adaptive histogram equalisation (tiles with bilinear blending). */
export function clahe(g: Gray, tiles = 8, clip = 2.5): Gray {
  const { w, h, data } = g
  const tw = Math.ceil(w / tiles)
  const th = Math.ceil(h / tiles)
  const luts: Uint8Array[] = []
  for (let ty = 0; ty < tiles; ty++) {
    for (let tx = 0; tx < tiles; tx++) {
      const x0 = tx * tw
      const y0 = ty * th
      const x1 = Math.min(w, x0 + tw)
      const y1 = Math.min(h, y0 + th)
      const hist = new Float32Array(256)
      let n = 0
      for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) {
          hist[data[y * w + x]]++
          n++
        }
      }
      const limit = Math.max(1, (clip * n) / 256)
      let excess = 0
      for (let i = 0; i < 256; i++) {
        if (hist[i] > limit) {
          excess += hist[i] - limit
          hist[i] = limit
        }
      }
      const add = excess / 256
      let acc = 0
      const lut = new Uint8Array(256)
      for (let i = 0; i < 256; i++) {
        acc += hist[i] + add
        lut[i] = Math.min(255, Math.round((acc / Math.max(1, n)) * 255))
      }
      luts.push(lut)
    }
  }
  const clampTile = (t: number) => Math.min(tiles - 1, Math.max(0, t))
  const out = new Uint8ClampedArray(w * h)
  for (let y = 0; y < h; y++) {
    const fy = (y + 0.5) / th - 0.5
    const ty0 = Math.floor(fy)
    const wy = fy - ty0
    const a = clampTile(ty0)
    const b = clampTile(ty0 + 1)
    for (let x = 0; x < w; x++) {
      const fx = (x + 0.5) / tw - 0.5
      const tx0 = Math.floor(fx)
      const wx = fx - tx0
      const c = clampTile(tx0)
      const d = clampTile(tx0 + 1)
      const v = data[y * w + x]
      const top = luts[a * tiles + c][v] * (1 - wx) + luts[a * tiles + d][v] * wx
      const bottom = luts[b * tiles + c][v] * (1 - wx) + luts[b * tiles + d][v] * wx
      out[y * w + x] = top * (1 - wy) + bottom * wy
    }
  }
  return { w, h, data: out }
}

/** Canny edges: Sobel gradients, non-maximum suppression, then double threshold with hysteresis. */
export function canny(g: Gray, low = 0.08, high = 0.2): Gray {
  const { w, h, data } = g
  const mag = new Float32Array(w * h)
  const dir = new Uint8Array(w * h)
  let max = 0
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x
      const gx = -data[i - w - 1] - 2 * data[i - 1] - data[i + w - 1] + data[i - w + 1] + 2 * data[i + 1] + data[i + w + 1]
      const gy = -data[i - w - 1] - 2 * data[i - w] - data[i - w + 1] + data[i + w - 1] + 2 * data[i + w] + data[i + w + 1]
      const m = Math.hypot(gx, gy)
      mag[i] = m
      if (m > max) max = m
      let a = (Math.atan2(gy, gx) * 180) / Math.PI
      if (a < 0) a += 180
      dir[i] = a < 22.5 || a >= 157.5 ? 0 : a < 67.5 ? 1 : a < 112.5 ? 2 : 3
    }
  }
  const nms = new Float32Array(w * h)
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x
      const m = mag[i]
      let n1: number
      let n2: number
      if (dir[i] === 0) {
        n1 = mag[i - 1]
        n2 = mag[i + 1]
      } else if (dir[i] === 1) {
        n1 = mag[i - w + 1]
        n2 = mag[i + w - 1]
      } else if (dir[i] === 2) {
        n1 = mag[i - w]
        n2 = mag[i + w]
      } else {
        n1 = mag[i - w - 1]
        n2 = mag[i + w + 1]
      }
      if (m >= n1 && m >= n2) nms[i] = m
    }
  }
  const lo = low * max
  const hi = high * max
  const out = new Uint8ClampedArray(w * h)
  const stack: number[] = []
  for (let i = 0; i < nms.length; i++) {
    if (nms[i] >= hi) {
      out[i] = 255
      stack.push(i)
    }
  }
  const around = [-w - 1, -w, -w + 1, -1, 1, w - 1, w, w + 1]
  while (stack.length) {
    const i = stack.pop()!
    for (const o of around) {
      const j = i + o
      if (j >= 0 && j < out.length && out[j] === 0 && nms[j] >= lo) {
        out[j] = 255
        stack.push(j)
      }
    }
  }
  return { w, h, data: out }
}

/**
 * Adaptive threshold: every pixel is compared with the average of its own neighbourhood (found quickly with an
 * integral image). A pixel darker than its surroundings by more than `offset` becomes white (a crease-like mark),
 * everything else black. It does not matter how bright the whole photo is.
 */
export function adaptiveThreshold(g: Gray, radius = 10, offset = 4): Gray {
  const { w, h, data } = g
  const stride = w + 1
  const sat = new Float64Array(stride * (h + 1))
  for (let y = 0; y < h; y++) {
    let row = 0
    for (let x = 0; x < w; x++) {
      row += data[y * w + x]
      sat[(y + 1) * stride + (x + 1)] = sat[y * stride + (x + 1)] + row
    }
  }
  const out = new Uint8ClampedArray(w * h)
  for (let y = 0; y < h; y++) {
    const y0 = Math.max(0, y - radius)
    const y1 = Math.min(h - 1, y + radius)
    for (let x = 0; x < w; x++) {
      const x0 = Math.max(0, x - radius)
      const x1 = Math.min(w - 1, x + radius)
      const area = (x1 - x0 + 1) * (y1 - y0 + 1)
      const sum = sat[(y1 + 1) * stride + (x1 + 1)] - sat[y0 * stride + (x1 + 1)] - sat[(y1 + 1) * stride + x0] + sat[y0 * stride + x0]
      out[y * w + x] = data[y * w + x] < sum / area - offset ? 255 : 0
    }
  }
  return { w, h, data: out }
}

/** One 3 x 3 pass on a black-and-white picture. `grow` spreads the white (dilate); otherwise it eats into it (erode). */
function morph(g: Gray, grow: boolean): Gray {
  const { w, h, data } = g
  const out = new Uint8ClampedArray(w * h)
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let v = grow ? 0 : 255
      for (let dy = -1; dy <= 1; dy++) {
        const yy = Math.min(h - 1, Math.max(0, y + dy))
        for (let dx = -1; dx <= 1; dx++) {
          const p = data[yy * w + Math.min(w - 1, Math.max(0, x + dx))]
          if (grow ? p > v : p < v) v = p
        }
      }
      out[y * w + x] = v
    }
  }
  return { w, h, data: out }
}

/**
 * Morphology: opening (erode, then dilate) removes tiny specks; closing (dilate, then erode) joins the pieces of a
 * line that a faint patch broke apart. What is left are cleaner, connected shapes for the next stage to follow.
 */
export function openClose(g: Gray): Gray {
  return morph(morph(morph(morph(g, false), true), true), false)
}

export function grayToCanvas(g: Gray, tint?: { base: [number, number, number]; bright: [number, number, number] }): HTMLCanvasElement {
  const c = document.createElement('canvas')
  c.width = g.w
  c.height = g.h
  const ctx = c.getContext('2d')!
  const img = ctx.createImageData(g.w, g.h)
  for (let i = 0, j = 0; i < g.data.length; i++, j += 4) {
    const v = g.data[i] / 255
    if (tint) {
      img.data[j] = tint.base[0] + (tint.bright[0] - tint.base[0]) * v
      img.data[j + 1] = tint.base[1] + (tint.bright[1] - tint.base[1]) * v
      img.data[j + 2] = tint.base[2] + (tint.bright[2] - tint.base[2]) * v
    } else {
      img.data[j] = img.data[j + 1] = img.data[j + 2] = g.data[i]
    }
    img.data[j + 3] = 255
  }
  ctx.putImageData(img, 0, 0)
  return c
}

export type PipelineStages = {
  original: HTMLCanvasElement
  gray: HTMLCanvasElement
  blur: HTMLCanvasElement
  contrast: HTMLCanvasElement
  edges: HTMLCanvasElement
  threshold: HTMLCanvasElement
  morphology: HTMLCanvasElement
}

/** Runs grayscale, Gaussian smoothing, CLAHE, Canny, thresholding and morphology on a picture and returns one canvas per stage. */
export function runPipeline(source: CanvasImageSource & { width: number; height: number }, maxSide = 560): PipelineStages {
  const scale = Math.min(1, maxSide / Math.max(source.width, source.height))
  const w = Math.max(2, Math.round(source.width * scale))
  const h = Math.max(2, Math.round(source.height * scale))
  const original = document.createElement('canvas')
  original.width = w
  original.height = h
  const ctx = original.getContext('2d', { willReadFrequently: true })!
  ctx.drawImage(source, 0, 0, w, h)

  const gray = toGray(ctx.getImageData(0, 0, w, h))
  const blurred = gaussianBlur(gray, 1.6)
  const contrast = clahe(blurred, 8, 2.6)
  const smooth = gaussianBlur(contrast, 1.3)
  const edges = canny(smooth, 0.1, 0.24)
  const threshold = adaptiveThreshold(smooth, 10, 4)
  const morphology = openClose(threshold)
  const tint = { base: [24, 18, 32] as [number, number, number], bright: [255, 214, 170] as [number, number, number] }
  return {
    original,
    gray: grayToCanvas(gray),
    blur: grayToCanvas(blurred),
    contrast: grayToCanvas(contrast),
    edges: grayToCanvas(edges, tint),
    threshold: grayToCanvas(threshold, tint),
    morphology: grayToCanvas(morphology, tint),
  }
}
