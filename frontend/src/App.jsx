import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'
const ACTIVE_KEY = 'zealflow_active_job'
const MAX_IMAGES = 99
const API_KEY_STORAGE = 'zealflow_openai_api_key'

const pretty = (value = '') => value.replaceAll('_', ' ')
const dateText = (value) => value ? new Date(value).toLocaleString() : '—'

function FileDrop({ title, subtitle, accept, multiple=false, file, files=[], onFiles, compact=false }) {
  const ref = useRef(null)
  const [drag, setDrag] = useState(false)
  const selectedCount = multiple ? files.length : (file ? 1 : 0)
  return <div className={`file-drop ${compact ? 'compact' : ''} ${drag ? 'drag' : ''} ${selectedCount ? 'selected' : ''}`}
    onDragOver={e => { e.preventDefault(); setDrag(true) }}
    onDragLeave={() => setDrag(false)}
    onDrop={e => { e.preventDefault(); setDrag(false); onFiles([...e.dataTransfer.files]) }}
    onClick={() => ref.current?.click()}>
    <input ref={ref} hidden type="file" accept={accept} multiple={multiple} onChange={e => onFiles([...e.target.files])}/>
    <div className="drop-icon">{selectedCount ? '✓' : '+'}</div>
    <div><strong>{title}</strong><span>{selectedCount ? (multiple ? `${selectedCount} image${selectedCount > 1 ? 's' : ''} selected` : file?.name) : subtitle}</span></div>
    <button type="button">{selectedCount ? 'Change' : 'Choose'}</button>
  </div>
}

function App() {
  const [view, setView] = useState('create')
  const [engine, setEngine] = useState('checking')
  const [frontRef, setFrontRef] = useState(null)
  const [backRef, setBackRef] = useState(null)
  const [rawFiles, setRawFiles] = useState([])
  const [zipFile, setZipFile] = useState(null)
  const [promptMode, setPromptMode] = useState('default')
  const [customPrompt, setCustomPrompt] = useState('')
  const [ratio, setRatio] = useState('auto')
  const [quality, setQuality] = useState('high')
  const [preservation, setPreservation] = useState('maximum')
  const [batchName, setBatchName] = useState('')
  const [job, setJob] = useState(null)
  const [history, setHistory] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [compareIndex, setCompareIndex] = useState(null)
  const [apiKey, setApiKey] = useState(() => localStorage.getItem(API_KEY_STORAGE) || '')
  const [apiKeyInput, setApiKeyInput] = useState(() => localStorage.getItem(API_KEY_STORAGE) || '')
  const [showApiKey, setShowApiKey] = useState(false)
  const [apiMessage, setApiMessage] = useState('')

  const processing = job?.status === 'processing'
  const finished = ['completed','completed_with_errors'].includes(job?.status)
  const percent = useMemo(() => !job?.total_images ? 0 : Math.round(job.completed_images / job.total_images * 100), [job])

  async function refreshHistory() {
    try { const r = await fetch(`${API}/api/jobs`); if (r.ok) setHistory(await r.json()) } catch {}
  }
  async function fetchJob(id, silent=true) {
    try {
      const r = await fetch(`${API}/api/jobs/${id}`)
      if (!r.ok) throw new Error('Batch not found')
      const data = await r.json(); setJob(data); return data
    } catch(e) { if (!silent) setError(e.message); return null }
  }

  useEffect(() => {
    fetch(`${API}/api/health`).then(r => r.ok ? r.json() : Promise.reject()).then(() => setEngine('ready')).catch(() => setEngine('offline'))
    refreshHistory()
    const active = localStorage.getItem(ACTIVE_KEY)
    if (active) fetchJob(active).then(d => { if (d) setView('results') })
  }, [])

  useEffect(() => {
    if (!processing || !job?.job_id) return
    const timer = setInterval(() => fetchJob(job.job_id), 2500)
    return () => clearInterval(timer)
  }, [processing, job?.job_id])

  useEffect(() => { if (finished) refreshHistory() }, [finished])

  function setReference(role, incoming) {
    const f = incoming[0]
    if (!f) return
    if (!f.type.startsWith('image/')) return setError('Reference must be an image.')
    setError(''); role === 'front' ? setFrontRef(f) : setBackRef(f)
  }
  function addRaw(incoming) {
    const valid = incoming.filter(f => f.type.startsWith('image/') || /\.(jpe?g|png|webp)$/i.test(f.name))
    const combined = [...rawFiles]
    for (const file of valid) {
      if (!combined.some(x => x.name === file.name && x.size === file.size)) combined.push(file)
    }
    if (combined.length > MAX_IMAGES) return setError(`Maximum ${MAX_IMAGES} direct images per batch.`)
    setRawFiles(combined); setError('')
  }
  function pickZip(incoming) {
    const f = incoming[0]
    if (!f) return
    if (!f.name.toLowerCase().endsWith('.zip')) return setError('Please choose a .zip file.')
    setZipFile(f); setError('')
  }

  function saveApiKey() {
    const value = apiKeyInput.trim()
    if (!value) { setApiMessage('Please enter your OpenAI API key.'); return }
    localStorage.setItem(API_KEY_STORAGE, value)
    setApiKey(value)
    setApiMessage('API key saved successfully.')
  }

  function removeApiKey() {
    localStorage.removeItem(API_KEY_STORAGE)
    setApiKey('')
    setApiKeyInput('')
    setApiMessage('API key removed.')
  }

  async function generate() {
    if (!apiKey.trim()) { setShowApiKey(true); return setError('Save your OpenAI API key before generating.') }
    if (!frontRef && !backRef) return setError('Add at least one reference image — Front or Back.')
    if (!rawFiles.length && !zipFile) return setError('Add raw images or a ZIP file.')
    if (promptMode === 'custom' && !customPrompt.trim()) return setError('Write your custom prompt or switch prompt mode.')
    setBusy(true); setError('')
    try {
      const form = new FormData()
      rawFiles.forEach(f => form.append('raw_images', f))
      if (zipFile) form.append('zip_file', zipFile)
      if (frontRef) form.append('reference_front', frontRef)
      if (backRef) form.append('reference_back', backRef)
      form.append('prompt_mode', promptMode)
      form.append('custom_prompt', customPrompt)
      form.append('aspect_ratio', ratio)
      form.append('quality', quality)
      form.append('preservation', preservation)
      form.append('batch_name', batchName)
      const create = await fetch(`${API}/api/jobs`, { method:'POST', body:form })
      const data = await create.json()
      if (!create.ok) throw new Error(data.detail || 'Could not create batch')
      setJob(data); localStorage.setItem(ACTIVE_KEY, data.job_id); setView('results')
      const start = await fetch(`${API}/api/jobs/${data.job_id}/start`, { method:'POST', headers:{ 'X-OpenAI-Key': apiKey } })
      if (!start.ok) { const d = await start.json(); throw new Error(d.detail || 'Could not start generation') }
      await fetchJob(data.job_id, false)
    } catch(e) { setError(e.message) } finally { setBusy(false) }
  }

  async function retry() {
    if (!job) return
    setBusy(true); setError('')
    try {
      if (!apiKey.trim()) { setShowApiKey(true); throw new Error('Save your OpenAI API key before retrying.') }
      const r = await fetch(`${API}/api/jobs/${job.job_id}/retry`, { method:'POST', headers:{ 'X-OpenAI-Key': apiKey } })
      const d = await r.json(); if (!r.ok) throw new Error(d.detail || 'Retry failed')
      await fetchJob(job.job_id, false)
    } catch(e) { setError(e.message) } finally { setBusy(false) }
  }

  function newBatch() {
    localStorage.removeItem(ACTIVE_KEY); setJob(null); setView('create'); setFrontRef(null); setBackRef(null); setRawFiles([]); setZipFile(null); setCustomPrompt(''); setPromptMode('default'); setBatchName(''); setError('')
  }

  async function openHistory(id) {
    const d = await fetchJob(id, false)
    if (d) { localStorage.setItem(ACTIVE_KEY, id); setView('results') }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="logo-wrap"><img src="/zeal-logo.png"/><div><strong>ZealFlow</strong><span>AI Image Studio</span></div></div>
      <nav>
        <button className={view === 'create' ? 'active':''} onClick={() => setView('create')}><i>＋</i>New Generation</button>
        <button className={view === 'history' ? 'active':''} onClick={() => {setView('history'); refreshHistory()}}><i>◷</i>History</button>
        <button className={showApiKey ? 'active':''} onClick={() => { setApiMessage(''); setApiKeyInput(apiKey); setShowApiKey(true) }}><i>⌘</i>API Key{apiKey && <span className="api-saved-dot"/>}</button>
        {job && <button className={view === 'results' ? 'active':''} onClick={() => setView('results')}><i>▦</i>Current Batch</button>}
      </nav>
      <div className={`engine ${engine}`}><i></i><div><strong>{engine === 'ready' ? 'Engine Ready' : engine === 'offline' ? 'Engine Offline' : 'Checking Engine'}</strong><span>OpenAI image pipeline</span></div></div>
    </aside>

    <div className="page">
      <header className="topbar"><div><span className="crumb">ZEALFLOW / {view === 'create' ? 'NEW GENERATION' : view.toUpperCase()}</span></div><button className="new-top" onClick={newBatch}>+ New Batch</button></header>

      {view === 'create' && <main className="content">
        <section className="title-row"><div><div className="eyebrow">REFERENCE-DRIVEN GENERATION</div><h1>Create a consistent visual batch.</h1><p>Add your reference look, import up to 99 raw images, then let ZealFlow apply the same visual direction across the batch.</p></div><div className="step-chip">01 → 04</div></section>

        <div className="builder-grid">
          <section className="card reference-card">
            <div className="card-head"><div className="step-no">01</div><div><h2>Reference Images</h2><p>Front, back, or both. At least one is required.</p></div><span className="required">REQUIRED</span></div>
            <div className="reference-grid">
              <ReferenceBox label="Front Reference" file={frontRef} onChange={f => setReference('front', f)}/>
              <ReferenceBox label="Back Reference" file={backRef} onChange={f => setReference('back', f)}/>
            </div>
            <div className="match-list"><span>Matches</span><b>Aspect ratio</b><b>Composition</b><b>Camera</b><b>Background</b><b>Lighting</b><b>Color tone</b><b>Pose</b><b>Look & feel</b></div>
          </section>

          <section className="card input-card">
            <div className="card-head"><div className="step-no">02</div><div><h2>Import Raw Inputs</h2><p>Upload images directly, a ZIP, or use both.</p></div><span className="count-badge">{rawFiles.length} / {MAX_IMAGES}</span></div>
            <FileDrop title="Raw Images" subtitle="JPG, PNG, WEBP · multi-select" accept="image/jpeg,image/png,image/webp" multiple files={rawFiles} onFiles={addRaw}/>
            <div className="or"><span>OR / ADD</span></div>
            <FileDrop compact title="ZIP File" subtitle="Import a folder as one ZIP" accept=".zip,application/zip" file={zipFile} onFiles={pickZip}/>
            {!!rawFiles.length && <div className="file-strip">{rawFiles.slice(0,6).map((f,i)=><span key={i}>{f.name}</span>)}{rawFiles.length>6 && <span>+{rawFiles.length-6} more</span>}<button onClick={() => setRawFiles([])}>Clear</button></div>}
          </section>

          <section className="card prompt-card">
            <div className="card-head"><div className="step-no">03</div><div><h2>Prompt</h2><p>Use ZealFlow defaults, add direction, or skip custom instructions.</p></div></div>
            <div className="segmented">{['default','custom','skip'].map(x => <button key={x} className={promptMode===x?'active':''} onClick={()=>setPromptMode(x)}>{x === 'default' ? 'Default' : x === 'custom' ? 'Custom' : 'Skip'}</button>)}</div>
            <textarea disabled={promptMode!=='custom'} value={customPrompt} onChange={e=>setCustomPrompt(e.target.value)} placeholder={promptMode==='custom' ? 'Example: Keep the same editorial lighting and full-body framing. Preserve garment artwork exactly...' : promptMode==='skip' ? 'No custom prompt. Internal source-preservation instructions will still run.' : 'ZealFlow universal reference-matching prompt is active.'}/>
          </section>

          <section className="card settings-card">
            <div className="card-head"><div className="step-no">04</div><div><h2>Output Settings</h2><p>Control framing, quality, and source fidelity.</p></div></div>
            <label className="field"><span>Batch Name <em>optional</em></span><input value={batchName} onChange={e=>setBatchName(e.target.value)} placeholder="e.g. CodeZ Winter Lookbook"/></label>
            <div className="field"><span>Aspect Ratio</span><div className="choice-grid ratio-grid">{['auto','1:1','4:5','3:4','9:16','16:9'].map(x=><button className={ratio===x?'selected':''} onClick={()=>setRatio(x)} key={x}>{x==='auto'?'Auto · Reference':x}</button>)}</div></div>
            <div className="two-fields"><div className="field"><span>Quality</span><div className="toggle-pair"><button className={quality==='standard'?'selected':''} onClick={()=>setQuality('standard')}>Standard</button><button className={quality==='high'?'selected':''} onClick={()=>setQuality('high')}>High</button></div></div><div className="field"><span>Preservation</span><div className="toggle-pair"><button className={preservation==='medium'?'selected':''} onClick={()=>setPreservation('medium')}>Medium</button><button className={preservation==='maximum'?'selected':''} onClick={()=>setPreservation('maximum')}>Maximum</button></div></div></div>
          </section>
        </div>

        {error && <div className="error-box">{error}</div>}
        <section className="launch-bar"><div><strong>{frontRef || backRef ? 'Reference ready' : 'Add a reference'}</strong><span>{rawFiles.length || zipFile ? `${rawFiles.length} direct image${rawFiles.length===1?'':'s'}${zipFile?' + ZIP':''}` : 'Import raw inputs to continue'}</span></div><button disabled={busy || engine!=='ready'} onClick={generate}>{busy ? 'Preparing Batch…' : 'Generate Batch'} <b>→</b></button></section>
      </main>}

      {view === 'results' && job && <Results job={job} percent={percent} API={API} error={error} busy={busy} retry={retry} newBatch={newBatch} compareIndex={compareIndex} setCompareIndex={setCompareIndex}/>} 

      {view === 'history' && <main className="content"><section className="title-row"><div><div className="eyebrow">SAVED LOCALLY</div><h1>Generation history.</h1><p>Re-open previous ZealFlow batches, inspect status, and download completed outputs.</p></div></section><section className="history-list">{history.length ? history.map(h=><button key={h.job_id} onClick={()=>openHistory(h.job_id)} className="history-row"><div className="history-icon">ZF</div><div className="history-main"><strong>{h.batch_name || `Batch ${h.job_id}`}</strong><span>{dateText(h.created_at)} · {h.total_images} images</span></div><div className={`mini-status ${h.status}`}>{pretty(h.status)}</div><div className="history-count">{h.completed_images}/{h.total_images}</div><b>→</b></button>) : <div className="empty-state">No batches yet. Create your first ZealFlow generation.</div>}</section></main>}
    </div>

    {showApiKey && <div className="modal api-key-modal-bg" onClick={()=>setShowApiKey(false)}>
      <div className="api-key-modal" onClick={e=>e.stopPropagation()}>
        <button className="close" onClick={()=>setShowApiKey(false)}>×</button>
        <div className="api-key-icon">⌘</div>
        <div className="eyebrow">ZEALFLOW SETTINGS</div>
        <h2>OpenAI API Key</h2>
        <p>Paste the key once on this browser. ZealFlow will use it automatically for Generate and Retry.</p>
        <label className="field"><span>API KEY</span><input type="password" value={apiKeyInput} onChange={e=>{setApiKeyInput(e.target.value);setApiMessage('')}} placeholder="sk-proj-..." autoComplete="off"/></label>
        {apiMessage && <div className="api-message">{apiMessage}</div>}
        <div className="api-key-status"><span>Status</span><strong className={apiKey?'connected':'not-connected'}>{apiKey?'● API Key Saved':'● API Key Not Added'}</strong></div>
        <div className="api-key-actions">{apiKey && <button type="button" className="remove-key" onClick={removeApiKey}>Remove Key</button>}<button type="button" className="save-key" onClick={saveApiKey}>Save API Key</button></div>
        <small className="api-note">Stored only in this browser. It is not written into ZealFlow history or source code.</small>
      </div>
    </div>}
  </div>
}

function ReferenceBox({label,file,onChange}) {
  const ref=useRef(null)
  const url=useMemo(()=>file?URL.createObjectURL(file):null,[file])
  useEffect(()=>()=>{if(url)URL.revokeObjectURL(url)},[url])
  return <div className={`reference-box ${file?'has-image':''}`} onClick={()=>ref.current?.click()}><input ref={ref} hidden type="file" accept="image/jpeg,image/png,image/webp" onChange={e=>onChange([...e.target.files])}/>{file ? <><img src={url}/><div className="ref-overlay"><strong>{label}</strong><span>Click to replace</span></div></> : <><div className="ref-plus">+</div><strong>{label}</strong><span>Upload image</span></>}</div>
}

function Results({job,percent,API,error,busy,retry,newBatch,compareIndex,setCompareIndex}) {
  const finished=['completed','completed_with_errors'].includes(job.status)
  return <main className="content">
    <section className="result-head"><div><div className="eyebrow">BATCH {job.job_id}</div><h1>{job.batch_name}</h1><p>{job.message}</p></div><div className={`status-pill ${job.status}`}>{pretty(job.status)}</div></section>
    <section className="stats"><div><span>Total</span><strong>{job.total_images}</strong></div><div><span>Completed</span><strong>{job.completed_images}</strong></div><div><span>Processing</span><strong>{job.processing_images}</strong></div><div><span>Issues</span><strong>{job.failed_images}</strong></div></section>
    <section className="progress-card"><div className="progress-top"><div><strong>{job.status==='processing' ? `Generating ${job.current_image || '…'}` : finished ? 'Generation complete' : 'Ready to generate'}</strong><span>{job.completed_images} of {job.total_images} completed</span></div><b>{percent}%</b></div><div className="progress"><i style={{width:`${percent}%`}}/></div><div className="result-actions">{job.zip_ready && <a href={`${API}/api/jobs/${job.job_id}/download`} className="red-btn">Download All ZIP ↓</a>}{job.failed_images>0 && finished && <button onClick={retry} disabled={busy}>Retry Failed</button>}<button onClick={newBatch}>+ New Batch</button></div></section>
    {error && <div className="error-box">{error}</div>}
    <section className="reference-summary"><div><span>Reference</span><strong>{job.references.map(r=>r.role).join(' + ')}</strong></div><div><span>Prompt</span><strong>{job.settings.prompt_mode}</strong></div><div><span>Ratio</span><strong>{job.settings.aspect_ratio}</strong></div><div><span>Quality</span><strong>{job.settings.quality}</strong></div><div><span>Preservation</span><strong>{job.settings.preservation}</strong></div></section>
    <section className="results-grid">{job.images.map((im,i)=><article className="result-card" key={`${im.filename}-${i}`}><div className="preview-pair"><div><span>Before</span><img src={`${API}/api/jobs/${job.job_id}/input/${i}`} loading="lazy"/></div><div className={im.status==='completed'?'':'placeholder'}><span>After</span>{im.status==='completed'?<img src={`${API}/api/jobs/${job.job_id}/output/${i}?v=${job.updated_at}`} loading="lazy"/>:<div className="pending">{im.status==='processing'?'Generating…':im.status==='failed'?'Failed':'Waiting'}</div>}</div></div><div className="result-meta"><div><strong>{im.filename}</strong><span className={im.status}>{pretty(im.status)}</span></div><div className="card-actions">{im.status==='completed' && <><button onClick={()=>setCompareIndex(i)}>Compare</button><a href={`${API}/api/jobs/${job.job_id}/output/${i}/download`}>Download</a></>}</div></div>{im.error && <small className="file-error">{im.error}</small>}</article>)}</section>
    {compareIndex!==null && <div className="modal" onClick={()=>setCompareIndex(null)}><div className="compare-modal" onClick={e=>e.stopPropagation()}><button className="close" onClick={()=>setCompareIndex(null)}>×</button><div><span>BEFORE</span><img src={`${API}/api/jobs/${job.job_id}/input/${compareIndex}`}/></div><div><span>AFTER</span><img src={`${API}/api/jobs/${job.job_id}/output/${compareIndex}`}/></div></div></div>}
  </main>
}

export default App
