import React, { useState, useRef, useEffect } from 'react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from './ui/card';
import { Textarea } from './ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import { Resizable } from 're-resizable';
import { ChevronRight, Send, Download } from 'lucide-react';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface ChatPanelProps {
  mode: 'chat' | 'mcp';
}

const ChatPanel: React.FC<ChatPanelProps> = ({ mode }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [jwtToken, setJwtToken] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sqlQuery, setSqlQuery] = useState('');
  const [results, setResults] = useState<any[] | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [mcpTrace, setMcpTrace] = useState<any | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom of messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Load JWT token from localStorage
  useEffect(() => {
    const savedToken = localStorage.getItem('jwt_token');
    if (savedToken) {
      setJwtToken(savedToken);
    }
  }, []);

  const handleSendMessage = async () => {
    if (!input.trim() || !jwtToken) return;

    // Save JWT token
    localStorage.setItem('jwt_token', jwtToken);

    // Add user message
    setMessages([...messages, { role: 'user', content: input }]);
    setIsLoading(true);

    try {
      if (mode === 'chat') {
        // Call /chat endpoint
        const response = await fetch('/chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${jwtToken}`
          },
          body: JSON.stringify({ query: input })
        });

        if (!response.ok) {
          throw new Error(`Error: ${response.status}`);
        }

        const data = await response.json();
        
        // Update state with response
        setMessages(prev => [...prev, { role: 'assistant', content: data.answer }]);
        setSqlQuery(data.sql);
        setResults(data.rows || null);
        setDownloadUrl(data.download_url || null);
        setMcpTrace(null);
      } else {
        // Call /mcp endpoint
        const response = await fetch('/mcp', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${jwtToken}`
          },
          body: JSON.stringify({
            trace_id: crypto.randomUUID(),
            context: { query: input },
            steps: [
              { tool: 'nl_to_sql' },
              { tool: 'sql_exec' },
              { tool: 'answer_format' }
            ]
          })
        });

        if (!response.ok) {
          throw new Error(`Error: ${response.status}`);
        }

        const data = await response.json();
        
        // Extract data from MCP response
        const nlToSqlStep = data.steps.find((s: any) => s.tool === 'nl_to_sql');
        const sqlExecStep = data.steps.find((s: any) => s.tool === 'sql_exec');
        const answerStep = data.steps.find((s: any) => s.tool === 'answer_format');
        
        // Update state with response
        setMessages(prev => [...prev, { role: 'assistant', content: answerStep?.output || 'No answer generated' }]);
        setSqlQuery(nlToSqlStep?.output?.sql || '');
        setResults(sqlExecStep?.output?.rows || null);
        setDownloadUrl(sqlExecStep?.output?.download_url || null);
        setMcpTrace(data);
      }
    } catch (error) {
      console.error('Error:', error);
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${error instanceof Error ? error.message : 'Unknown error'}` }]);
    } finally {
      setIsLoading(false);
      setInput('');
    }
  };

  return (
    <Resizable
      defaultSize={{ width: '100%', height: 600 }}
      minHeight={300}
      maxHeight={800}
      enable={{ top: true, bottom: true }}
      className="border rounded-lg shadow-md bg-white"
    >
      <Card className="h-full flex flex-col">
        <CardHeader className="pb-2">
          <CardTitle>{mode === 'chat' ? 'SQL Assistant' : 'MCP Service'}</CardTitle>
          <div className="mt-2">
            <Input
              placeholder="Enter JWT token with fleet_id claim"
              value={jwtToken}
              onChange={(e) => setJwtToken(e.target.value)}
              className="mb-2"
            />
          </div>
        </CardHeader>
        
        <CardContent className="flex-grow overflow-auto p-4">
          <div className="space-y-4">
            {messages.map((message, index) => (
              <div 
                key={index} 
                className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div 
                  className={`max-w-[80%] rounded-lg p-3 ${
                    message.role === 'user' 
                      ? 'bg-blue-500 text-white' 
                      : 'bg-gray-100 text-gray-800'
                  }`}
                >
                  {message.content}
                </div>
              </div>
            ))}
            {isLoading && (
              <div className="flex justify-start">
                <div className="max-w-[80%] rounded-lg p-3 bg-gray-100">
                  <div className="flex items-center space-x-2">
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </CardContent>
        
        <div className="px-4">
          {(sqlQuery || results || downloadUrl || mcpTrace) && (
            <Tabs defaultValue="sql" className="w-full mb-4">
              <TabsList className="grid w-full grid-cols-4">
                <TabsTrigger value="sql">SQL</TabsTrigger>
                <TabsTrigger value="results">Results</TabsTrigger>
                {mode === 'mcp' && <TabsTrigger value="trace">MCP Trace</TabsTrigger>}
                {downloadUrl && <TabsTrigger value="download">Download</TabsTrigger>}
              </TabsList>
              
              <TabsContent value="sql" className="mt-2">
                <Textarea 
                  value={sqlQuery} 
                  readOnly 
                  className="font-mono text-sm h-32 overflow-auto"
                />
              </TabsContent>
              
              <TabsContent value="results" className="mt-2">
                {results ? (
                  <div className="overflow-auto max-h-32">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          {Object.keys(results[0]).map((key) => (
                            <th 
                              key={key}
                              className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                            >
                              {key}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {results.map((row, i) => (
                          <tr key={i}>
                            {Object.values(row).map((value: any, j) => (
                              <td key={j} className="px-3 py-2 text-sm text-gray-500">
                                {value !== null ? String(value) : ''}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : downloadUrl ? (
                  <div className="text-center p-4">
                    <p>Large result set available for download</p>
                  </div>
                ) : (
                  <div className="text-center p-4">No results available</div>
                )}
              </TabsContent>
              
              {mode === 'mcp' && (
                <TabsContent value="trace" className="mt-2">
                  <Textarea 
                    value={mcpTrace ? JSON.stringify(mcpTrace, null, 2) : ''} 
                    readOnly 
                    className="font-mono text-sm h-32 overflow-auto"
                  />
                </TabsContent>
              )}
              
              {downloadUrl && (
                <TabsContent value="download" className="mt-2">
                  <div className="flex justify-center items-center h-32">
                    <a 
                      href={downloadUrl} 
                      download 
                      className="flex items-center space-x-2 bg-blue-500 text-white px-4 py-2 rounded-md hover:bg-blue-600"
                    >
                      <Download size={16} />
                      <span>Download CSV</span>
                    </a>
                  </div>
                </TabsContent>
              )}
            </Tabs>
          )}
        </div>
        
        <CardFooter className="flex items-center space-x-2 pt-2">
          <Input
            placeholder="Ask a question about your fleet..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
            disabled={isLoading}
          />
          <Button 
            onClick={handleSendMessage} 
            disabled={isLoading || !input.trim() || !jwtToken}
            size="icon"
          >
            <Send size={16} />
          </Button>
        </CardFooter>
      </Card>
    </Resizable>
  );
};

export default ChatPanel;
