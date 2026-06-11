import React from 'react'

export const Card: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ children, className = '', ...props }) => {
  return (
    <div
      className={`bg-sand backdrop-blur-md border border-sand-border rounded-2xl shadow-xl ${className}`}
      {...props}
    >
      {children}
    </div>
  )
}

export const CardHeader: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ children, className = '', ...props }) => {
  return <div className={`p-6 pb-3 flex flex-col gap-1.5 ${className}`} {...props}>{children}</div>
}

export const CardTitle: React.FC<React.HTMLAttributes<HTMLHeadingElement>> = ({ children, className = '', ...props }) => {
  return <h3 className={`font-display text-lg font-semibold text-ink tracking-tight ${className}`} {...props}>{children}</h3>
}

export const CardDescription: React.FC<React.HTMLAttributes<HTMLParagraphElement>> = ({ children, className = '', ...props }) => {
  return <p className={`text-sm text-muted ${className}`} {...props}>{children}</p>
}

export const CardContent: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ children, className = '', ...props }) => {
  return <div className={`p-6 pt-3 ${className}`} {...props}>{children}</div>
}

export const CardFooter: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ children, className = '', ...props }) => {
  return <div className={`p-6 pt-3 border-t border-sand-border flex items-center justify-end gap-3 ${className}`} {...props}>{children}</div>
}
