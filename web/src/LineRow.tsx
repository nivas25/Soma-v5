type Line = { id: number; nick: string; text: string; reply_to: number | null }

export function LineRow({
  line,
  lines,
  currentNick,
  time,
}: {
  line: Line
  lines: Line[]
  currentNick?: string
  time?: string
}) {
  const soma = line.nick.toLowerCase() === "soma"
  const isMe = Boolean(currentNick && line.nick.toLowerCase() === currentNick.toLowerCase())
  const quoted = soma ? lines.find((item) => item.id === line.reply_to) : undefined
  const displayTime = time || new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })

  return (
    <div className={`msg-in flex w-full ${isMe ? "justify-end" : "justify-start"}`}>
      <div
        className={`relative max-w-[85%] sm:max-w-[72%] break-words px-4 py-2.5 transition-all ${
          isMe
            ? "rounded-2xl rounded-tr-xs bg-[#e2f2ee] text-neutral-900"
            : soma
            ? "rounded-2xl rounded-tl-xs bg-[#e4eee8] text-neutral-900"
            : "rounded-2xl rounded-tl-xs bg-neutral-100 text-neutral-900"
        }`}
      >
        <p
          className={`text-xs ${
            soma
              ? "font-bold text-[#094e43] flex items-center gap-1.5"
              : isMe
              ? "font-bold text-[#094e43] text-right"
              : "font-bold text-neutral-600"
          }`}
        >
          {soma ? (
            <>
              <span className="font-soma">SOMA</span>
              <span className="text-[10px] font-semibold bg-[#094e43]/10 px-1.5 py-0.5 rounded-full text-[#094e43]">
                AI
              </span>
            </>
          ) : isMe ? (
            "You"
          ) : (
            line.nick
          )}
        </p>
        {quoted ? (
          <p className="mt-1.5 border-l-2 border-[#8aa394] pl-2 text-xs sm:text-sm text-[#3d4a42] italic bg-neutral-900/5 rounded-r-md py-1 pr-2">
            "{quoted.text}"
          </p>
        ) : null}
        <div className="mt-1 flex items-end justify-between gap-3">
          <p className="text-[15px] sm:text-base leading-relaxed text-neutral-900 flex-1">{line.text}</p>
          <span
            className={`text-[11px] select-none shrink-0 leading-tight mb-0.5 font-medium ${
              isMe ? "text-[#094e43]/60" : "text-neutral-400"
            }`}
          >
            {displayTime}
          </span>
        </div>
      </div>
    </div>
  )
}
