import * as ScrollAreaPrimitive from "@radix-ui/react-scroll-area"
import * as React from "react"

import { cn } from "@/lib/utils"

function ScrollArea({ className, children, ...props }: React.ComponentProps<typeof ScrollAreaPrimitive.Root>) {
  return (
    <ScrollAreaPrimitive.Root className={cn("relative overflow-hidden", className)} {...props}>
      <ScrollAreaPrimitive.Viewport className="h-full w-full">{children}</ScrollAreaPrimitive.Viewport>
      <ScrollAreaPrimitive.ScrollAreaScrollbar
        orientation="vertical"
        className="flex w-2 touch-none select-none p-0.5 transition-colors"
      >
        <ScrollAreaPrimitive.ScrollAreaThumb className="relative flex-1 rounded-full bg-neutral-300 hover:bg-neutral-400" />
      </ScrollAreaPrimitive.ScrollAreaScrollbar>
    </ScrollAreaPrimitive.Root>
  )
}

export { ScrollArea }
