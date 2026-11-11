"use client";

import React, { useState, useEffect, useRef } from 'react';

const glassCardLight = "bg-white/40 backdrop-blur-2xl border border-white/50 shadow-[0_4px_20px_rgb(0,0,0,0.04)]";
const glassItemLight = "bg-white/50 backdrop-blur-xl border border-white/60 shadow-sm";
const glassInputLight = "bg-white/30 backdrop-blur-xl border border-white/50 text-slate-800 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-400/40 focus:bg-white/50 transition-all duration-300 shadow-inner";
const textGradientDark = "bg-gradient-to-br from-slate-900 to-slate-600 text-transparent bg-clip-text";

export default function FormulaAIDashboard() {
  const [prompt, setPrompt] = useState('Design a bio-pesticide for aphids that is stable in sunlight.');
  const [activeIngredient, setActiveIngredient] = useState('Beauveria bassiana');
  const [targetPest, setTargetPest] = useState('Aphids');
  const [payloadType, setPayloadType] = useState('microbe');

  const [isRunning, setIsRunning] = useState(false);
  const [events, setEvents] = useState<Array<{ node: string; content: string; icon: string; color: string }>>([]);
  const [finalStatus, setFinalStatus] = useState<string | null>(null);
  const [recipe, setRecipe] = useState<Array<{ role: string; name: string; amount: string; citation?: string }> | null>(null);

  const [island, setIsland] = useState({
    state: 'idle' as 'idle' | 'loading' | 'notification',
    title: 'FormulaAI',
    subtitle: '',
    message: '',
    icon: '✨'
  });

  const wsRef = useRef<WebSocket | null>(null);

  const handleStartPipeline = (e: React.FormEvent) => {
    e.preventDefault();
    if (isRunning) return;

    setIsRunning(true);
    setFinalStatus(null);
    setRecipe(null);
    setEvents([]);

    setIsland({
      state: 'loading',
      title: 'Orchestrating',
      subtitle: 'Initiating workflow...',
      icon: '⚙️',
      message: ''
    });

    try {
      const ws = new WebSocket("ws://localhost:8000/ws/agent-stream");
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({
          user_prompt: prompt,
          active_ingredient: activeIngredient,
          target_pest: targetPest,
          payload_type: payloadType
        }));
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === 'node_start') {
          setIsland({
            state: 'loading',
            title: data.node,
            subtitle: 'Analyzing formulation parameters...',
            icon: data.node.includes('chemist') ? '🧪' : data.node.includes('biostability') ? '🧬' : '⚠️',
            message: ''
          });
        } else if (data.type === 'message') {
          const icon = data.node.includes('chemist') ? '🧪' : data.node.includes('biostability') ? '🧬' : '⚠️';
          const color = data.node.includes('chemist')
            ? 'bg-blue-100 text-blue-700 border-blue-200'
            : data.node.includes('biostability')
            ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
            : 'bg-amber-100 text-amber-700 border-amber-200';

          setEvents(prev => [...prev, { node: data.node, content: data.content, icon, color }]);

          setIsland({
            state: 'notification',
            title: data.node,
            message: data.content,
            icon,
            subtitle: ''
          });
        } else if (data.type === 'error') {
          setEvents(prev => [...prev, { node: '❌ System Error', content: data.message, icon: '⚠️', color: 'bg-red-100 text-red-700 border-red-200' }]);
          setIsland({
            state: 'notification',
            title: 'Pipeline Error',
            message: data.message,
            icon: '❌',
            subtitle: ''
          });
        } else if (data.type === 'status') {
          setFinalStatus(data.status);
          if (data.status === 'APPROVED' && data.recipe) {
            setRecipe(data.recipe);
          }
        } else if (data.type === 'pipeline_complete') {
          setIsRunning(false);
          if (island.state !== 'notification' || !island.title.includes('Error')) {
            setIsland({ state: 'idle', title: 'FormulaAI', subtitle: '', message: '', icon: '✨' });
          }
          ws.close();
        }
      };

      ws.onerror = () => {
        setIsRunning(false);
        setEvents(prev => [...prev, { node: '❌ Connection Error', content: 'WebSocket connection failed. Ensure FastAPI backend is running on port 8000.', icon: '⚠️', color: 'bg-red-100 text-red-700 border-red-200' }]);
        setIsland({
          state: 'notification',
          title: 'Connection Lost',
          message: 'Cannot reach backend. Run: uvicorn main:app --reload --port 8000',
          icon: '❌',
          subtitle: ''
        });
        setTimeout(() => {
          setIsland({ state: 'idle', title: 'FormulaAI', subtitle: '', message: '', icon: '✨' });
        }, 8000);
      };

    } catch (err: any) {
      console.error(err);
      setIsRunning(false);
      setIsland({
        state: 'notification',
        title: 'Unexpected Error',
        message: err?.message || 'An unknown error occurred',
        icon: '❌',
        subtitle: ''
      });
      setTimeout(() => {
        setIsland({ state: 'idle', title: 'FormulaAI', subtitle: '', message: '', icon: '✨' });
      }, 8000);
    }
  };

  const getIslandStyles = () => {
    switch (island.state) {
      case 'loading':
        return "w-72 h-11 rounded-full bg-black/90 backdrop-blur-2xl border border-white/10 px-4 py-2";
      case 'notification':
        return "w-[440px] sm:w-[500px] min-h-[100px] rounded-[32px] bg-black/90 backdrop-blur-2xl border border-white/10 p-5";
      default:
        return "w-44 h-10 rounded-full bg-black/90 backdrop-blur-2xl border border-white/10 px-4 py-2";
    }
  };

  return (
    <div className="relative min-h-screen bg-[#f2f4f8] overflow-hidden font-sans flex flex-col items-center">

      <div className="absolute top-[-15%] left-[-10%] w-[60vw] h-[60vw] bg-blue-300/40 rounded-full mix-blend-multiply filter blur-[120px] animate-pulse"></div>
      <div className="absolute bottom-[-15%] right-[-10%] w-[70vw] h-[70vw] bg-purple-300/30 rounded-full mix-blend-multiply filter blur-[140px] animate-pulse" style={{ animationDelay: '2s' }}></div>
      <div className="absolute top-[25%] right-[15%] w-[45vw] h-[45vw] bg-pink-200/40 rounded-full mix-blend-multiply filter blur-[100px] animate-pulse" style={{ animationDelay: '4s' }}></div>

      <div className={`fixed top-4 z-50 flex flex-col justify-center items-center shadow-[0_20px_50px_rgba(0,0,0,0.25)] transition-all duration-300 ease-in-out text-white overflow-hidden ${getIslandStyles()}`}>

        {island.state === 'idle' && (
          <div className="flex items-center gap-2 transition-opacity duration-300">
            <span className="text-xs">{island.icon}</span>
            <span className="text-xs font-semibold tracking-wide">{island.title}</span>
          </div>
        )}

        {island.state === 'loading' && (
          <div className="flex items-center justify-between w-full px-2 transition-opacity duration-300">
            <div className="flex items-center gap-3 truncate">
              <span className="text-sm animate-pulse">{island.icon}</span>
              <span className="text-xs font-medium tracking-wide truncate">{island.title}</span>
            </div>
            <div className="flex items-center gap-1.5 shrink-0 ml-2">
              <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce"></span>
              <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></span>
              <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></span>
            </div>
          </div>
        )}

        {island.state === 'notification' && (
          <div className="flex flex-col w-full h-full justify-between transition-opacity duration-300">
            <div className="flex items-center gap-3 mb-2">
              <div className="w-7 h-7 rounded-full bg-white/20 flex items-center justify-center text-xs shrink-0">
                {island.icon}
              </div>
              <span className="text-xs font-semibold tracking-wide text-white/90 truncate">{island.title}</span>
            </div>
            <div className="text-xs text-white/80 leading-relaxed font-light line-clamp-3">
              {island.message}
            </div>
          </div>
        )}
      </div>

      <div className="w-full max-w-[1400px] mt-24 px-6 sm:px-8 pb-8 flex flex-col lg:flex-row items-start gap-6 lg:gap-8 z-10 min-h-[calc(100vh-120px)]">

        <div className={`w-full lg:w-1/3 rounded-[40px] p-8 flex flex-col self-start ${glassCardLight}`}>
          <div className="mb-8">
            <h1 className={`text-4xl font-extrabold tracking-tight mb-2 ${textGradientDark}`}>FormulaAI</h1>
            <p className="text-sm text-slate-600 font-medium">Agentic Formulation Design</p>
          </div>

          <form onSubmit={handleStartPipeline} className="flex-1 flex flex-col gap-6 overflow-y-auto pr-2 custom-scrollbar">
            <div className="space-y-2.5">
              <label className="text-[11px] font-bold text-slate-500 uppercase tracking-wider ml-2">Active Ingredient</label>
              <input type="text" value={activeIngredient} onChange={e => setActiveIngredient(e.target.value)} disabled={isRunning}
                className={`w-full rounded-3xl px-5 py-4 text-sm font-medium ${glassInputLight} disabled:opacity-50`} />
            </div>

            <div className="space-y-2.5">
              <label className="text-[11px] font-bold text-slate-500 uppercase tracking-wider ml-2">Target Pest / Pathogen</label>
              <input type="text" value={targetPest} onChange={e => setTargetPest(e.target.value)} disabled={isRunning}
                className={`w-full rounded-3xl px-5 py-4 text-sm font-medium ${glassInputLight} disabled:opacity-50`} />
            </div>

            <div className="space-y-2.5">
              <label className="text-[11px] font-bold text-slate-500 uppercase tracking-wider ml-2">Payload Classification</label>
              <div className="relative">
                <select value={payloadType} onChange={e => setPayloadType(e.target.value)} disabled={isRunning}
                  className={`w-full rounded-3xl px-5 py-4 text-sm font-medium appearance-none ${glassInputLight} disabled:opacity-50`}>
                  <option value="chemical">Synthetic Chemical</option>
                  <option value="peptide">Peptide / Protein</option>
                  <option value="microbe">Microbial (Bacteria/Fungi)</option>
                  <option value="rnai">Nucleic Acid (RNAi)</option>
                </select>
                <div className="absolute right-5 top-1/2 -translate-y-1/2 pointer-events-none text-slate-400">▼</div>
              </div>
            </div>

            <div className="space-y-2.5 flex-1 flex flex-col">
              <label className="text-[11px] font-bold text-slate-500 uppercase tracking-wider ml-2">Design Constraints</label>
              <textarea value={prompt} onChange={e => setPrompt(e.target.value)} disabled={isRunning}
                className={`w-full flex-1 min-h-[120px] rounded-3xl px-5 py-4 text-sm font-medium resize-none ${glassInputLight} disabled:opacity-50`} />
            </div>

            <button type="submit" disabled={isRunning}
              className={`mt-2 w-full py-4 rounded-3xl font-bold tracking-wide transition-all duration-300 backdrop-blur-md
                ${isRunning
                  ? 'bg-slate-300/50 text-slate-500 cursor-not-allowed border border-white/40'
                  : 'bg-blue-600/90 hover:bg-blue-600 text-white shadow-[0_4px_20px_rgba(37,99,235,0.3)] hover:shadow-[0_6px_25px_rgba(37,99,235,0.4)] hover:-translate-y-0.5 border border-blue-400/50'
                }`}>
              {isRunning ? 'Processing via Agents...' : 'Initiate Discovery'}
            </button>
          </form>
        </div>

        <div className={`w-full lg:w-2/3 rounded-[40px] p-8 flex flex-col ${glassCardLight} relative overflow-hidden`}>
          <div className="flex items-center justify-between mb-8 px-2">
            <div>
              <h2 className={`text-3xl font-extrabold tracking-tight ${textGradientDark}`}>Formulation Profile</h2>
              <p className="text-sm text-slate-600 mt-1 font-medium">System output and compliance status</p>
            </div>
            {finalStatus && (
              <span className={`px-5 py-2.5 text-[11px] font-bold uppercase tracking-wider rounded-full shadow-sm backdrop-blur-md ${
                finalStatus === 'APPROVED' ? 'bg-emerald-400/20 text-emerald-800 border border-emerald-300/50' :
                'bg-red-400/20 text-red-800 border border-red-300/50'
              }`}>
                {finalStatus}
              </span>
            )}
          </div>

          <div className="flex-1 overflow-y-auto pr-4 custom-scrollbar space-y-8">

            <div className={`rounded-[32px] p-6 ${glassCardLight}`}>
              <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-5 ml-2">Recommended Protocol</h3>

              {recipe ? (
                <div className="space-y-3">
                  {recipe.map((item, idx) => (
                    <div key={idx} className={`rounded-[24px] p-4 flex justify-between items-center transition-all hover:bg-white/60 ${glassItemLight}`}>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">{item.role}</span>
                        <div className="flex items-center gap-2.5 flex-wrap">
                          <span className="text-sm text-slate-800 font-bold">{item.name}</span>
                          {item.citation && (
                            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-blue-600 bg-blue-50/90 hover:bg-blue-100/90 px-2.5 py-0.5 rounded-full border border-blue-200/60 shadow-sm transition-all duration-200 cursor-default" title={`Knowledge Graph Validation: ${item.citation}`}>
                              <svg className="w-3 h-3 text-blue-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                              </svg>
                              <span className="truncate max-w-[240px]">{item.citation}</span>
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="text-right shrink-0 ml-4">
                        <span className="text-sm font-mono text-blue-700 bg-blue-50/50 px-4 py-2 rounded-2xl border border-blue-200/50 backdrop-blur-sm shadow-inner">{item.amount}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="h-48 flex flex-col items-center justify-center text-slate-500 text-sm font-medium text-center">
                  {isRunning ? (
                    <div className="flex flex-col items-center gap-4 animate-pulse">
                      <div className="w-10 h-10 border-4 border-blue-500/30 border-t-blue-600 rounded-full animate-spin"></div>
                      <span>Formulating optimal excipient matrix...</span>
                    </div>
                  ) : (
                    <>
                      <span className="text-3xl mb-2">📋</span>
                      <span>Awaiting parameters to generate protocol.</span>
                    </>
                  )}
                </div>
              )}
            </div>

            {/* Section 2: Agent Audit Trail */}
            {events.length > 0 && (
              <div className={`rounded-[32px] p-6 ${glassCardLight}`}>
                <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-6 ml-2">Agent Audit Trail</h3>

                <div className="space-y-0">
                  {events.map((ev, idx) => (
                    <div key={idx} className={`relative flex gap-5 py-5 ${idx !== events.length - 1 ? 'border-b border-white/30' : ''}`}>
                      {idx !== events.length - 1 && (
                        <div className="absolute left-[19px] top-14 bottom-[-20px] w-[2px] bg-white/40"></div>
                      )}

                      <div className="flex-shrink-0 z-10">
                        <div className={`w-10 h-10 rounded-full flex items-center justify-center text-lg shadow-sm border ${ev.color} backdrop-blur-md`}>
                          {ev.icon}
                        </div>
                      </div>

                      <div className="flex flex-col pt-1.5 w-full">
                        <span className="text-[12px] font-bold text-slate-800 tracking-wide mb-2">{ev.node}</span>
                        <div className={`text-[13px] text-slate-800 leading-relaxed font-medium p-5 rounded-3xl rounded-tl-none ${glassItemLight}`}>
                          {ev.content}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

          </div>
        </div>

      </div>
    </div>
  );
}