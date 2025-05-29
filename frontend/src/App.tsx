import React, { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './components/ui/tabs';
import ChatPanel from './components/ChatPanel';
import { ResizablePanel, ResizablePanelGroup } from './components/ui/resizable';
import { Button } from './components/ui/button';
import { MoveHorizontal } from 'lucide-react';

function App() {
  const [layout, setLayout] = useState<'single' | 'split'>('single');
  const [activeTab, setActiveTab] = useState<'chat' | 'mcp'>('chat');

  const toggleLayout = () => {
    setLayout(layout === 'single' ? 'split' : 'single');
  };

  return (
    <div className="container mx-auto p-4">
      <header className="mb-6">
        <h1 className="text-3xl font-bold mb-2">SQL Assistant</h1>
        <p className="text-gray-600">
          A natural-language analytics layer for fleet operators
        </p>
      </header>

      <div className="mb-4 flex justify-between items-center">
        {layout === 'single' ? (
          <Tabs 
            value={activeTab} 
            onValueChange={(value) => setActiveTab(value as 'chat' | 'mcp')}
            className="w-full"
          >
            <TabsList className="grid w-60 grid-cols-2">
              <TabsTrigger value="chat">SQL Assistant</TabsTrigger>
              <TabsTrigger value="mcp">MCP Service</TabsTrigger>
            </TabsList>
          </Tabs>
        ) : (
          <div className="text-lg font-medium">Split View</div>
        )}
        
        <Button 
          variant="outline" 
          size="sm" 
          onClick={toggleLayout}
          className="ml-4"
        >
          <MoveHorizontal className="mr-2 h-4 w-4" />
          {layout === 'single' ? 'Split View' : 'Single View'}
        </Button>
      </div>

      {layout === 'single' ? (
        <div>
          {activeTab === 'chat' ? (
            <ChatPanel mode="chat" />
          ) : (
            <ChatPanel mode="mcp" />
          )}
        </div>
      ) : (
        <ResizablePanelGroup direction="horizontal" className="min-h-[600px]">
          <ResizablePanel defaultSize={50}>
            <div className="p-2">
              <h2 className="text-lg font-medium mb-2">SQL Assistant</h2>
              <ChatPanel mode="chat" />
            </div>
          </ResizablePanel>
          <ResizablePanel defaultSize={50}>
            <div className="p-2">
              <h2 className="text-lg font-medium mb-2">MCP Service</h2>
              <ChatPanel mode="mcp" />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      )}

      <footer className="mt-8 text-center text-gray-500 text-sm">
        <p>© 2025 SQL Assistant. All rights reserved.</p>
      </footer>
    </div>
  );
}

export default App;
