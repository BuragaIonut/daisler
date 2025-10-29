'use client'

import { useState, useRef } from 'react'
import { Upload, Download, Image as ImageIcon, FileText, Settings, Loader2 } from 'lucide-react'

export default function Home() {
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string>('')
  const [processing, setProcessing] = useState(false)
  const [result, setResult] = useState<Blob | null>(null)
  const [error, setError] = useState<string>('')
  
  // Form settings
  const [width, setWidth] = useState<string>('150')
  const [height, setHeight] = useState<string>('180')
  const [unit, setUnit] = useState<string>('mm')
  const [dpi, setDpi] = useState<string>('300')
  const [addBleed, setAddBleed] = useState<boolean>(true)
  const [bleedSize, setBleedSize] = useState<string>('3')

  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      setFile(selectedFile)
      setError('')
      setResult(null)
      
      // Create preview
      const reader = new FileReader()
      reader.onload = (event) => {
        setPreviewUrl(event.target?.result as string)
      }
      reader.readAsDataURL(selectedFile)
    }
  }

  const handleProcess = async () => {
    if (!file) {
      setError('Please upload a file first')
      return
    }

    setProcessing(true)
    setError('')
    setResult(null)

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('target_width', width)
      formData.append('target_height', height)
      formData.append('unit', unit)
      formData.append('dpi', dpi)
      formData.append('add_bleed', addBleed.toString())
      formData.append('bleed_mm', bleedSize)

      const response = await fetch('/api/process_for_print', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Processing failed')
      }

      const blob = await response.blob()
      setResult(blob)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Processing failed')
    } finally {
      setProcessing(false)
    }
  }

  const handleDownload = () => {
    if (!result) return

    const url = URL.createObjectURL(result)
    const a = document.createElement('a')
    a.href = url
    a.download = 'print_ready.pdf'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const handleReset = () => {
    setFile(null)
    setPreviewUrl('')
    setResult(null)
    setError('')
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900 p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-5xl font-bold text-white mb-4">
            Print Production Studio
          </h1>
          <p className="text-slate-300 text-lg">
            AI-powered image processing for professional print
          </p>
        </div>

        <div className="grid lg:grid-cols-2 gap-8">
          {/* Left Column - Upload & Settings */}
          <div className="space-y-6">
            {/* Upload Card */}
            <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-8 border border-white/20">
              <h2 className="text-2xl font-semibold text-white mb-6 flex items-center gap-2">
                <Upload className="w-6 h-6" />
                Upload File
              </h2>
              
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*,application/pdf"
                onChange={handleFileChange}
                className="hidden"
                id="file-upload"
              />
              
              <label
                htmlFor="file-upload"
                className="block w-full cursor-pointer"
              >
                <div className="border-2 border-dashed border-white/30 rounded-xl p-12 text-center hover:border-purple-400 transition-colors">
                  {previewUrl ? (
                    <div className="space-y-4">
                      <img
                        src={previewUrl}
                        alt="Preview"
                        className="max-h-48 mx-auto rounded-lg shadow-lg"
                      />
                      <p className="text-white font-medium">{file?.name}</p>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.preventDefault()
                          handleReset()
                        }}
                        className="text-purple-400 hover:text-purple-300 text-sm"
                      >
                        Change file
                      </button>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <ImageIcon className="w-16 h-16 mx-auto text-white/50" />
                      <p className="text-white text-lg">
                        Click to upload image or PDF
                      </p>
                      <p className="text-slate-400 text-sm">
                        Supports JPG, PNG, PDF
                      </p>
                    </div>
                  )}
                </div>
              </label>
            </div>

            {/* Settings Card */}
            <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-8 border border-white/20">
              <h2 className="text-2xl font-semibold text-white mb-6 flex items-center gap-2">
                <Settings className="w-6 h-6" />
                Print Settings
              </h2>
              
              <div className="space-y-6">
                {/* Dimensions */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-white mb-2 text-sm font-medium">
                      Width
                    </label>
                    <input
                      type="number"
                      value={width}
                      onChange={(e) => setWidth(e.target.value)}
                      className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                      placeholder="150"
                    />
                  </div>
                  <div>
                    <label className="block text-white mb-2 text-sm font-medium">
                      Height
                    </label>
                    <input
                      type="number"
                      value={height}
                      onChange={(e) => setHeight(e.target.value)}
                      className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                      placeholder="180"
                    />
                  </div>
                </div>

                {/* Unit */}
                <div>
                  <label className="block text-white mb-2 text-sm font-medium">
                    Unit
                  </label>
                  <select
                    value={unit}
                    onChange={(e) => setUnit(e.target.value)}
                    className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                  >
                    <option value="mm">Millimeters (mm)</option>
                    <option value="inch">Inches</option>
                  </select>
                </div>

                {/* DPI */}
                <div>
                  <label className="block text-white mb-2 text-sm font-medium">
                    DPI (Resolution)
                  </label>
                  <input
                    type="number"
                    value={dpi}
                    onChange={(e) => setDpi(e.target.value)}
                    className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                    placeholder="300"
                  />
                </div>

                {/* Bleed Settings */}
                <div className="space-y-4">
                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      id="add-bleed"
                      checked={addBleed}
                      onChange={(e) => setAddBleed(e.target.checked)}
                      className="w-5 h-5 rounded border-white/20 bg-white/5 text-purple-500 focus:ring-2 focus:ring-purple-500"
                    />
                    <label htmlFor="add-bleed" className="text-white font-medium">
                      Add Bleed
                    </label>
                  </div>
                  
                  {addBleed && (
                    <div>
                      <label className="block text-white mb-2 text-sm font-medium">
                        Bleed Size (mm)
                      </label>
                      <input
                        type="number"
                        value={bleedSize}
                        onChange={(e) => setBleedSize(e.target.value)}
                        className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                        placeholder="3"
                        step="0.5"
                      />
                    </div>
                  )}
                </div>

                {/* Process Button */}
                <button
                  onClick={handleProcess}
                  disabled={!file || processing}
                  className="w-full py-4 px-6 bg-gradient-to-r from-purple-600 to-pink-600 text-white rounded-lg font-semibold text-lg hover:from-purple-700 hover:to-pink-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg hover:shadow-xl flex items-center justify-center gap-2"
                >
                  {processing ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" />
                      Processing...
                    </>
                  ) : (
                    <>
                      <FileText className="w-5 h-5" />
                      Process for Print
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>

          {/* Right Column - Results */}
          <div className="space-y-6">
            {/* Workflow Info */}
            <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-8 border border-white/20">
              <h2 className="text-2xl font-semibold text-white mb-6">
                Workflow
              </h2>
              <ol className="space-y-3 text-slate-300">
                <li className="flex items-start gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-purple-500 text-white flex items-center justify-center text-sm font-bold">
                    1
                  </span>
                  <span>Upload image or PDF (converts to image)</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-purple-500 text-white flex items-center justify-center text-sm font-bold">
                    2
                  </span>
                  <span>Calculate dimensions and aspect ratio</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-purple-500 text-white flex items-center justify-center text-sm font-bold">
                    3
                  </span>
                  <span>Determine extension strategy</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-purple-500 text-white flex items-center justify-center text-sm font-bold">
                    4
                  </span>
                  <span>AI extension (if aspect ratio mismatch)</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-purple-500 text-white flex items-center justify-center text-sm font-bold">
                    5
                  </span>
                  <span>Add mirror bleed (seamless edges)</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-purple-500 text-white flex items-center justify-center text-sm font-bold">
                    6
                  </span>
                  <span>Upscale to target DPI with LANCZOS</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-purple-500 text-white flex items-center justify-center text-sm font-bold">
                    7
                  </span>
                  <span>Convert to PDF with CutContour spot color</span>
                </li>
              </ol>
            </div>

            {/* Error Display */}
            {error && (
              <div className="bg-red-500/20 backdrop-blur-lg rounded-2xl p-6 border border-red-500/50">
                <p className="text-red-200 font-medium">Error: {error}</p>
              </div>
            )}

            {/* Success Display */}
            {result && (
              <div className="bg-green-500/20 backdrop-blur-lg rounded-2xl p-8 border border-green-500/50">
                <h3 className="text-2xl font-semibold text-white mb-4">
                  ✓ Processing Complete!
                </h3>
                <p className="text-green-200 mb-6">
                  Your print-ready PDF is ready to download.
                </p>
                <button
                  onClick={handleDownload}
                  className="w-full py-4 px-6 bg-gradient-to-r from-green-600 to-emerald-600 text-white rounded-lg font-semibold text-lg hover:from-green-700 hover:to-emerald-700 transition-all shadow-lg hover:shadow-xl flex items-center justify-center gap-2"
                >
                  <Download className="w-5 h-5" />
                  Download PDF
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  )
}
