/**
 * Compress an image and convert it to a raw base64 string (without data URL prefix).
 * Resizes the image so that its maximum dimension is 1024px, maintaining aspect ratio,
 * and compresses it with JPEG format at 0.8 quality.
 */
export const compressAndEncodeImage = (file: File): Promise<string> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.readAsDataURL(file)
    reader.onload = (event) => {
      const img = new Image()
      img.src = event.target?.result as string
      img.onload = () => {
        const canvas = document.createElement('canvas')
        let width = img.width
        let height = img.height
        const maxDimension = 1024

        // Maintain aspect ratio while capping max dimension
        if (width > height) {
          if (width > maxDimension) {
            height = Math.round((height * maxDimension) / width)
            width = maxDimension
          }
        } else {
          if (height > maxDimension) {
            width = Math.round((width * maxDimension) / height)
            height = maxDimension
          }
        }

        canvas.width = width
        canvas.height = height

        const ctx = canvas.getContext('2d')
        if (!ctx) {
          reject(new Error('Failed to get canvas context'))
          return
        }

        // Draw image to canvas
        ctx.drawImage(img, 0, 0, width, height)

        // Export to JPEG base64 at 0.8 quality
        const dataUrl = canvas.toDataURL('image/jpeg', 0.8)
        
        // Strip the data URL header to get only raw base64 data
        const base64Data = dataUrl.split(',')[1]
        resolve(base64Data)
      }
      img.onerror = (err) => {
        reject(err)
      }
    }
    reader.onerror = (err) => {
      reject(err)
    }
  })
}
