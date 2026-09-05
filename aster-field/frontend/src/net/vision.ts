export interface PendingImage {
  full: string;
  thumb: string;
}

export function scaleImage(file: File, maxSide: number, quality: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, maxSide / Math.max(img.width, img.height));
      const cv = document.createElement('canvas');
      cv.width = Math.round(img.width * k);
      cv.height = Math.round(img.height * k);
      cv.getContext('2d')!.drawImage(img, 0, 0, cv.width, cv.height);
      resolve(cv.toDataURL('image/jpeg', quality));
    };
    img.onerror = () => reject(new Error('image decode failed'));
    img.src = URL.createObjectURL(file);
  });
}

export async function prepareImage(file: File): Promise<PendingImage> {
  const [full, thumb] = await Promise.all([
    scaleImage(file, 1280, 0.82),
    scaleImage(file, 220, 0.7),
  ]);
  return { full, thumb };
}
