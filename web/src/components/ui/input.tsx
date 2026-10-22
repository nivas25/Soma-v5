import * as React from "react"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      className={cn(
        "flex h-11 w-full border-0 bg-white px-3 text-base text-neutral-900 outline-none placeholder:text-neutral-400 focus-visible:outline-none",
        className,
      )}
      {...props}
    />
  )
}

export { Input }
