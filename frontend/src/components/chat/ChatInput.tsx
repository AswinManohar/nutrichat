import { useRef, useState } from 'react'
import { compressAndEncodeImage } from '../../lib/image'
import { Camera, ArrowUp, X } from 'lucide-react'

interface ChatInputProps {
  onSend: (text: string, imageB64?: string | null) => void
  isLoading: boolean
}

export function ChatInput({ onSend, isLoading }: ChatInputProps) {
  const [text, setText] = useState('')
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const [imageB64, setImageB64] = useState<string | null>(null)
  const [compressing, setCompressing] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleImageChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setCompressing(true)
    try {
      setImagePreview(URL.createObjectURL(file))
      setImageB64(await compressAndEncodeImage(file))
    } catch (err) {
      console.error('Error processing image:', err)
      setImagePreview(null)
      setImageB64(null)
    } finally {
      setCompressing(false)
    }
  }

  const handleRemoveImage = () => {
    setImagePreview(null)
    setImageB64(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleSend = () => {
    if (!text.trim() && !imageB64) return
    onSend(text, imageB64)
    setText('')
    handleRemoveImage()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col gap-2 px-4 md:px-8 pb-4 pt-2 bg-surface sticky bottom-0 z-30">
      {/* Image preview chip */}
      {imagePreview && (
        <div className="card-sand flex items-center gap-3 p-2 self-start rise-in">
          <div className="w-11 h-11 rounded-lg overflow-hidden relative">
            <img src={imagePreview} alt="upload preview" className="w-full h-full object-cover" />
            {compressing && (
              <div className="absolute inset-0 bg-surface/80 flex items-center justify-center">
                <span className="w-3 h-3 border border-t-transparent border-sage rounded-full animate-spin" />
              </div>
            )}
          </div>
          <span className="text-[12px] text-ink-soft">{compressing ? 'Compressing…' : 'Photo attached'}</span>
          <button
            type="button"
            onClick={handleRemoveImage}
            className="press w-6 h-6 rounded-full bg-container text-muted hover:text-ink flex items-center justify-center"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* Input pill */}
      <div className="flex items-end gap-2 bg-paper border border-sand-border rounded-[26px] p-2 shadow-[0_4px_12px_rgba(0,0,0,0.03)] focus-within:border-sage transition-colors duration-300">
        <input type="file" accept="image/*" ref={fileInputRef} onChange={handleImageChange} className="hidden" />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isLoading || compressing}
          className="press w-10 h-10 shrink-0 flex items-center justify-center text-muted hover:text-sage-deep hover:bg-container rounded-full disabled:opacity-30"
          title="Add a food photo"
        >
          <Camera className="w-5 h-5" strokeWidth={1.75} />
        </button>

        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={imageB64 ? 'Add a note, or just send…' : 'A bowl of oatmeal with blueberries…'}
          rows={1}
          disabled={isLoading}
          className="flex-1 bg-transparent text-ink placeholder-muted focus:outline-none resize-none max-h-32 min-h-10 py-2.5 text-[15px] leading-normal"
        />

        <button
          type="button"
          onClick={handleSend}
          disabled={isLoading || compressing || (!text.trim() && !imageB64)}
          className="press w-10 h-10 shrink-0 flex items-center justify-center bg-sage hover:bg-sage-deep text-white rounded-full disabled:opacity-30 transition-colors duration-300"
        >
          <ArrowUp className="w-5 h-5" strokeWidth={2} />
        </button>
      </div>
    </div>
  )
}
