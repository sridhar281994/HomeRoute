export async function requestBrowserMediaAccess(options?: { video?: boolean; audio?: boolean }): Promise<void> {
  const media = navigator.mediaDevices;
  if (!media || !media.getUserMedia) {
    throw new Error("Media access not supported in this browser/device.");
  }
  const stream = await media.getUserMedia({
    video: options?.video ?? true,
    audio: options?.audio ?? false,
  });
  stream.getTracks().forEach((track) => track.stop());
}
