/** Contenu base64 d'un Blob (sans le préfixe data:…;base64,) — pour Filesystem.writeFile. */
export function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    // "data:audio/mpeg;base64,<data>" → on ne garde que <data>
    reader.onload  = () => resolve((reader.result as string).split(',')[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}
