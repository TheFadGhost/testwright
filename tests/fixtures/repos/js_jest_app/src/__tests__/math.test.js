const { add } = require('../math');

describe('math', () => {
  it('add(1, 2) is 3', () => {
    expect(add(1, 2)).toEqual(3);
  });
});
