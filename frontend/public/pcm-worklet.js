// AudioWorklet: converts microphone audio to 16 kHz mono PCM16 frames (~20 ms each)
// and reports the RMS level of every frame for voice activity detection.
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetRate = (options && options.processorOptions && options.processorOptions.targetRate) || 16000;
    this.ratio = sampleRate / this.targetRate; // `sampleRate` is a global in the worklet scope
    this.frameSize = Math.round(this.targetRate * 0.02); // 320 samples = 20 ms
    this.frame = new Int16Array(this.frameSize);
    this.frameIdx = 0;
    this.sumSq = 0;
    this.pos = 0; // fractional read position into the input stream
    this.carry = new Float32Array(0);
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0]) return true;

    // mix down to mono
    const ch0 = input[0];
    let mono = ch0;
    if (input.length > 1) {
      mono = new Float32Array(ch0.length);
      for (let c = 0; c < input.length; c++) {
        const ch = input[c];
        for (let i = 0; i < ch.length; i++) mono[i] += ch[i] / input.length;
      }
    }

    // prepend leftover samples from the previous block
    const buf = new Float32Array(this.carry.length + mono.length);
    buf.set(this.carry, 0);
    buf.set(mono, this.carry.length);

    // box-filter downsampling (averages the samples each output sample covers)
    while (this.pos + this.ratio <= buf.length) {
      const start = Math.floor(this.pos);
      const end = Math.floor(this.pos + this.ratio);
      let acc = 0;
      for (let i = start; i < end; i++) acc += buf[i];
      const s = Math.max(-1, Math.min(1, acc / Math.max(1, end - start)));
      this.frame[this.frameIdx++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      this.sumSq += s * s;
      this.pos += this.ratio;

      if (this.frameIdx === this.frameSize) {
        const out = this.frame.slice(0);
        this.port.postMessage({ pcm: out.buffer, rms: Math.sqrt(this.sumSq / this.frameSize) }, [out.buffer]);
        this.frameIdx = 0;
        this.sumSq = 0;
      }
    }
    const consumed = Math.floor(this.pos);
    this.carry = buf.slice(consumed);
    this.pos -= consumed;
    return true;
  }
}

registerProcessor("pcm-capture", PcmCaptureProcessor);
